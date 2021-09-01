#!/usr/bin/env python
import sys
import math
import time
import rospy
import copy
import numpy as np
import tf
import moveit_commander
import helper
import motion_primitives
import tilt
import yaml
import actionlib
import visualization
import dynamixel 
import random
import globals as gbs

from robotiq_2f_gripper_msgs.msg import CommandRobotiqGripperFeedback, CommandRobotiqGripperResult, CommandRobotiqGripperAction, CommandRobotiqGripperGoal
from robotiq_2f_gripper_control.robotiq_2f_gripper_driver import Robotiq2FingerGripperDriver as Robotiq

moveit_commander.roscpp_initialize(sys.argv)
robot = moveit_commander.RobotCommander() 
scene = moveit_commander.PlanningSceneInterface() 
group = moveit_commander.MoveGroupCommander("manipulator") 

def regrasp(axis, angle, velocity):
    pose_target = group.get_current_pose().pose
    pos_initial = [pose_target.position.x, pose_target.position.y, pose_target.position.z]
    ori_initial = [pose_target.orientation.x, pose_target.orientation.y, pose_target.orientation.z, pose_target.orientation.w]
    T_we = tf.TransformListener().fromTranslationRotation(pos_initial, ori_initial) 
    tcp2fingertip = gbs.config['tcp2fingertip']
    contact_A_e = [tcp2fingertip, gbs.config['object_thickness']/2, 0, 1] #TODO: depends on axis direction #-config['object_thickness']/2
    contact_A_w = np.matmul(T_we, contact_A_e) 

    #visualization.visualizer(contact_A_w[:3], "s", 0.01, 1) #DEBUG

    # Interpolate orientation poses via quaternion slerp
    q = helper.axis_angle2quaternion(axis, angle)
    ori_target = tf.transformations.quaternion_multiply(q, ori_initial)    
    ori_waypoints = helper.slerp(ori_initial, ori_target, np.arange(1.0/angle , 1.0+1.0/angle, 1.0/angle)) 

    theta_0 = gbs.config['theta_0']
    waypoints = []
    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)
    for psi in range(1, angle+1):
        # Calculate width
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c

        # Calculate position 
        if theta_0 + psi <= 90:
            hori =  math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi)))
            verti =  math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi))) - math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi)))
        else:
            hori = -math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi-90)))
            verti = math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi-90)))

        if axis[0] > 0:
            pose_target.position.y = contact_A_w[1] + hori
            pose_target.position.z = contact_A_w[2] + verti
            #print "CASE 1"
        elif axis[0] < 0:
            pose_target.position.y = contact_A_w[1] + verti #- hori
            pose_target.position.z = contact_A_w[2] + hori #+ verti
            #print "CASE 2"
        elif axis[1] > 0:
            pose_target.position.x = contact_A_w[0] - verti #white boardplacing #- hori
            pose_target.position.z = contact_A_w[2] - hori #+ verti
            #print "CASE 3"
        elif axis[1] < 0:
            pose_target.position.x = contact_A_w[0] - verti #whiteboard270placing #+ hori
            pose_target.position.z = contact_A_w[2] + hori #+ verti
            #print "CASE 4"

        pose_target.orientation.x = ori_waypoints[psi-1][0]
        pose_target.orientation.y = ori_waypoints[psi-1][1]
        pose_target.orientation.z = ori_waypoints[psi-1][2]
        pose_target.orientation.w = ori_waypoints[psi-1][3]
        waypoints.append(copy.deepcopy(pose_target))
    (plan, fraction) = group.compute_cartesian_path(waypoints, 0.01, 0) 
    retimed_plan = group.retime_trajectory(robot.get_current_state(), plan, velocity) 
    group.execute(retimed_plan, wait=False)

    
    opening_at_zero = gbs.config['max_opening']-2*gbs.config['finger_thickness']
    psi = 0
    while psi < angle:
        pose = group.get_current_pose().pose
        q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
        psi = 2*math.degrees(math.acos(np.dot(q_current, ori_initial)))
        if psi > 100:
            psi = -(psi-360)
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c
        Robotiq.goto(robotiq_client, pos=width+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #0.006 for coin; 0.000 for book; 0.005 for poker
        #Robotiq.goto(robotiq_client, pos=width+gbs.config['gripper_offset']-0.00028*(psi/angle), speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #coin
        psi = round(psi, 2)
        rospy.sleep(0.5) 
    return width

def palm_regrasp(axis, angle, velocity):
    pose_target = group.get_current_pose().pose
    pos_initial = [pose_target.position.x, pose_target.position.y, pose_target.position.z]
    ori_initial = [pose_target.orientation.x, pose_target.orientation.y, pose_target.orientation.z, pose_target.orientation.w]
    T_we = tf.TransformListener().fromTranslationRotation(pos_initial, ori_initial) 
    tcp2fingertip = gbs.config['tcp2fingertip']   
    contact_A_e = [tcp2fingertip, -gbs.config['object_thickness']/2, 0, 1] #TODO: depends on axis direction
    contact_A_w = np.matmul(T_we, contact_A_e) 

    #visualization.visualizer(contact_A_w[:3], "s", 0.01, 1) #DEBUG

    # Interpolate orientation poses via quaternion slerp
    q = helper.axis_angle2quaternion(axis, angle)
    ori_target = tf.transformations.quaternion_multiply(q, ori_initial)    
    ori_waypoints = helper.slerp(ori_initial, ori_target, np.arange(1.0/angle , 1.0+1.0/angle, 1.0/angle)) 

    theta_0 = gbs.config['theta_0']
    waypoints = []
    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)
        
    for psi in range(1, angle+1):
        # Calculate width
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c

        # Calculate position 
        if theta_0 + psi <= 90:
            hori =  math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi)))
            verti =  math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi))) - math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi)))
        else:
            hori = -math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi-90)))
            verti = math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi-90)))
        
        '''
        #Left Vertical Case
        if axis[0] > 0:
            pose_target.position.y = contact_A_w[1] - verti
            pose_target.position.z = contact_A_w[2] + hori
            #print "CASE 1"
        #Right Vertical Case
        elif axis[0] < 0:
            pose_target.position.y = contact_A_w[1] - verti
            pose_target.position.z = contact_A_w[2] - hori
            #print "CASE 2"
        '''
        
        if axis[0] > 0:
            pose_target.position.y = contact_A_w[1] + hori
            pose_target.position.z = contact_A_w[2] + verti
            #print "CASE 1"
        #Normal Case
        elif axis[0] < 0:
            pose_target.position.y = contact_A_w[1] - hori #(- +) ( + + ) ( + -)
            pose_target.position.z = contact_A_w[2] + verti
            #print "CASE 2"
        elif axis[1] > 0:
            pose_target.position.x = contact_A_w[0] - verti #- hori
            pose_target.position.z = contact_A_w[2] - hori #+ verti
            #print "CASE 3"
        elif axis[1] < 0:
            pose_target.position.x = contact_A_w[0] - verti #+ hori
            pose_target.position.z = contact_A_w[2] + hori #+ verti
            #print "CASE 4"
        
        pose_target.orientation.x = ori_waypoints[psi-1][0]
        pose_target.orientation.y = ori_waypoints[psi-1][1]
        pose_target.orientation.z = ori_waypoints[psi-1][2]
        pose_target.orientation.w = ori_waypoints[psi-1][3]
        waypoints.append(copy.deepcopy(pose_target))
    (plan, fraction) = group.compute_cartesian_path(waypoints, 0.01, 0) 
    retimed_plan = group.retime_trajectory(robot.get_current_state(), plan, velocity) 
    group.execute(retimed_plan, wait=False)

    
    opening_at_zero = gbs.config['max_opening']-2*gbs.config['finger_thickness']
    psi = 0
    while psi < angle:
        pose = group.get_current_pose().pose
        q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
        psi = 2*math.degrees(math.acos(np.dot(q_current, ori_initial)))
        if psi > 100:
            psi = -(psi-360)
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c
        palm_position = 128 + 1.2*(gbs.config['delta_0'] - a)*1000
        #pos = int((opening_at_zero - width)/config['opening_per_count'])
        Robotiq.goto(robotiq_client, pos=width+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #offset:0.005
        print palm_position
        dynamixel.set_length(palm_position)
        psi = round(psi, 2)
        rospy.sleep(0.5) 
       
def inverted_palm_regrasp(axis, angle, velocity):
    pose_target = group.get_current_pose().pose
    pos_initial = [pose_target.position.x, pose_target.position.y, pose_target.position.z]
    ori_initial = [pose_target.orientation.x, pose_target.orientation.y, pose_target.orientation.z, pose_target.orientation.w]
    T_we = tf.TransformListener().fromTranslationRotation(pos_initial, ori_initial) 
    tcp2fingertip = gbs.config['tcp2fingertip']
    contact_A_e = [tcp2fingertip, gbs.config['object_thickness']/2, 0, 1] #TODO: depends on axis direction
    contact_A_w = np.matmul(T_we, contact_A_e) 

    #visualization.visualizer(contact_A_w[:3], "s", 0.01, 1) #DEBUG

    # Interpolate orientation poses via quaternion slerp
    q = helper.axis_angle2quaternion(axis, angle)
    ori_target = tf.transformations.quaternion_multiply(q, ori_initial)    
    ori_waypoints = helper.slerp(ori_initial, ori_target, np.arange(1.0/angle , 1.0+1.0/angle, 1.0/angle)) 

    theta_0 = gbs.config['theta_0']
    waypoints = []
    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)
        
    for psi in range(1, angle+1):
        # Calculate width
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c

        # Calculate position 
        if theta_0 + psi <= 90:
            hori =  math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi)))
            verti =  math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi))) - math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi)))
        else:
            hori = -math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi-90)))
            verti = math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi-90)))

        if axis[0] > 0:
            pose_target.position.y = contact_A_w[1] - hori # TODO: The only thing I changed for inverted palm regrasp is the (-) sign
            pose_target.position.z = contact_A_w[2] - verti
            #print "CASE 1"
        elif axis[0] < 0:
            pose_target.position.y = contact_A_w[1] + hori
            pose_target.position.z = contact_A_w[2] - verti
            #print "CASE 2"
        elif axis[1] > 0:
            pose_target.position.x = contact_A_w[0] - hori
            pose_target.position.z = contact_A_w[2] + verti
            #print "CASE 3"
        elif axis[1] < 0:
            pose_target.position.x = contact_A_w[0] + hori
            pose_target.position.z = contact_A_w[2] + verti
            #print "CASE 4"

        pose_target.orientation.x = ori_waypoints[psi-1][0]
        pose_target.orientation.y = ori_waypoints[psi-1][1]
        pose_target.orientation.z = ori_waypoints[psi-1][2]
        pose_target.orientation.w = ori_waypoints[psi-1][3]
        waypoints.append(copy.deepcopy(pose_target))
    (plan, fraction) = group.compute_cartesian_path(waypoints, 0.01, 0) 
    retimed_plan = group.retime_trajectory(robot.get_current_state(), plan, velocity) 
    group.execute(retimed_plan, wait=False)

    
    opening_at_zero = gbs.config['max_opening']-2*gbs.config['finger_thickness']
    psi = 0
    while psi < angle:
        pose = group.get_current_pose().pose
        q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
        psi = 2*math.degrees(math.acos(np.dot(q_current, ori_initial)))
        if psi > 100:
            psi = -(psi-360)
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c
        palm_position = 127 + (gbs.config['delta_0'] - a)*1000
        #pos = int((opening_at_zero - width)/config['opening_per_count'])
        Robotiq.goto(robotiq_client, pos=width+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #offset:0.003
        dynamixel.set_length(palm_position+9)
        psi = round(psi, 2)


def second_regrasp(axis, angle, pos, velocity):
    tcp2fingertip = gbs.config['tcp2fingertip']
    
    p = group.get_current_pose().pose
    trans_tool0 = [p.position.x, p.position.y, p.position.z]
    rot_tool0 = [p.orientation.x, p.orientation.y, p.orientation.z, p.orientation.w] 
    T_wg = tf.TransformerROS().fromTranslationRotation(trans_tool0, rot_tool0)
    P_g_center = [tcp2fingertip+0.02, -pos/2.0, 0, 1]
    P_w_center = np.matmul(T_wg, P_g_center)
    center = [P_w_center[0], P_w_center[1], P_w_center[2]]
    waypoints = tilt.tilt_no_wait(center, axis, int(angle), velocity)
    #print waypoints
    rospy.sleep(0.5)
    
    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)

    current_angle = 0
    while current_angle < angle:
        pose = group.get_current_pose().pose
        q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
        current_angle = 2*math.degrees(math.acos(np.dot(q_current, rot_tool0)))
        if current_angle > 100:
            current_angle = -(psi-360)
        Robotiq.goto(robotiq_client, pos=pos+0.00315+0.012*(current_angle/angle), speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) 

        current_angle = round(current_angle, 2)
 
def active_regrasp(axis, angle, velocity, active_distance, psi_active_transition, active_distance_2):
    pose_target = group.get_current_pose().pose
    pos_initial = [pose_target.position.x, pose_target.position.y, pose_target.position.z]
    ori_initial = [pose_target.orientation.x, pose_target.orientation.y, pose_target.orientation.z, pose_target.orientation.w]
    T_we = tf.TransformListener().fromTranslationRotation(pos_initial, ori_initial) 
    tcp2fingertip = gbs.config['tcp2fingertip']
    error = 0.00
    contact_A_e = [tcp2fingertip+random.uniform(-error, error), -gbs.config['object_thickness']/2+random.uniform(-error, error), 0, 1] #TODO: depends on axis direction
    contact_A_w = np.matmul(T_we, contact_A_e) 

    #visualization.visualizer(contact_A_w[:3], "s", 0.01, 1) #DEBUG

    # Interpolate orientation poses via quaternion slerp
    q = helper.axis_angle2quaternion(axis, angle)
    ori_target = tf.transformations.quaternion_multiply(q, ori_initial)    
    ori_waypoints = helper.slerp(ori_initial, ori_target, np.arange(1.0/angle , 1.0+1.0/angle, 1.0/angle)) 

    theta_0 = gbs.config['theta_0']
    waypoints = []
    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)
    for psi in range(1, angle+1):
        # Calculate width
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c

        # Calculate position 
        if theta_0 + psi <= 90:
            hori =  math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi)))
            verti =  math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi))) - math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi)))
        else:
            hori = -math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi-90)))
            verti = math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi-90)))

        if axis[0] > 0:
            pose_target.position.y = contact_A_w[1] + hori
            pose_target.position.z = contact_A_w[2] + verti
            print "CASE 1"
        elif axis[0] < 0:
            if psi <= psi_active_transition:
                pose_target.position.y = contact_A_w[1] - hori - active_distance*psi/psi_active_transition
            else:
                pose_target.position.y = contact_A_w[1] - hori - active_distance + active_distance_2*(psi-psi_active_transition)/(angle+1-psi_active_transition)
            pose_target.position.z = contact_A_w[2] + verti
            print "CASE 2"
        elif axis[1] > 0:
            pose_target.position.x = contact_A_w[0] - hori
            pose_target.position.z = contact_A_w[2] + verti
            print "CASE 3"
        elif axis[1] < 0:
            pose_target.position.x = contact_A_w[0] + hori
            pose_target.position.z = contact_A_w[2] + verti
            print "CASE 4"

        pose_target.orientation.x = ori_waypoints[psi-1][0]
        pose_target.orientation.y = ori_waypoints[psi-1][1]
        pose_target.orientation.z = ori_waypoints[psi-1][2]
        pose_target.orientation.w = ori_waypoints[psi-1][3]
        waypoints.append(copy.deepcopy(pose_target))
    (plan, fraction) = group.compute_cartesian_path(waypoints, 0.01, 0) 
    retimed_plan = group.retime_trajectory(robot.get_current_state(), plan, velocity) 
    group.execute(retimed_plan, wait=False)

    
    opening_at_zero = gbs.config['max_opening']-2*gbs.config['finger_thickness']
    psi = 0
    while psi < angle:
        pose = group.get_current_pose().pose
        q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
        psi = 2*math.degrees(math.acos(np.dot(q_current, ori_initial)))
        if psi > 100:
            psi = -(psi-360)
        a = gbs.config['delta_0'] * math.cos(math.radians(psi))
        b = gbs.config['delta_0'] * math.sin(math.radians(psi))
        c = gbs.config['object_thickness'] * math.cos(math.radians(psi))
        d = gbs.config['object_thickness'] * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c
        #pos = int((opening_at_zero - width)/config['opening_per_count'])
        Robotiq.goto(robotiq_client, pos=width+0.000, speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #0.006 for coin; 0.000 for book; 0.005 for poker
        #if psi < 1.0 or psi > 47.0: 
        #print "psi= ", psi, "          width= ", width
        psi = round(psi, 2)
        rospy.sleep(0.5) # TESTING TO SEE IF THE GRIPPER ACTION DOESNT LAG
    return width

def slide_release(axis, B_slide_distance, width, velocity):
    '''Release primitive motion of sliding both A and B towards the tip of the object with the gripper closing kinematically

    Parameters:
        axis (list): 3-D vector of rotation axis (right-hand rule) (same as the axis of regrasp)
        B_slide_distance (double): the distance to slide at B (+ve for sliding the object out of the gripper)
        width (double): the width of the gripper after the regrasp primitive (obtain by the return value of regrasp)
        velocity (double): robot velocity between 0 and 1

    '''

    theta_0 = gbs.config['theta_0']
    delta_0 = gbs.config['delta_0']
    psi_regrasp = gbs.config['psi_regrasp']

    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)

    pose_initial = group.get_current_pose().pose
    pos_initial = np.array((pose_initial.position.x, pose_initial.position.y, pose_initial.position.z))

    width_final = width - math.tan(math.radians(psi_regrasp)) * B_slide_distance
    gripper_offset = (width - width_final)/2 #for keeping thumb fixed and finger moving towards thumb
    offset_hori = gripper_offset*math.fabs(math.sin(math.radians(theta_0 + psi_regrasp)))
    offset_verti = gripper_offset*math.fabs(math.cos(math.radians(theta_0 + psi_regrasp)))
    
    slide_hori = B_slide_distance*math.fabs(math.cos(math.radians(theta_0 + psi_regrasp)))
    slide_verti = B_slide_distance*math.fabs(math.sin(math.radians(theta_0 + psi_regrasp)))
    translation_final = math.sqrt((slide_hori+offset_hori)**2 + (slide_verti+offset_verti)**2) #length of total sliding translation

    if axis[0] > 0:
        motion_primitives.linear_path([0, slide_hori + offset_hori, slide_verti - offset_verti], velocity, False)
    elif axis[0] < 0:
        motion_primitives.linear_path([0, -slide_hori - offset_hori, slide_verti - offset_verti], velocity, False)
    elif axis[1] > 0:
        motion_primitives.linear_path([-slide_hori - offset_hori, 0, slide_verti - offset_verti], velocity, False)
    elif axis[1] < 0:
        motion_primitives.linear_path([slide_hori + offset_hori, 0, slide_verti - offset_verti], velocity, False)

    #gripper motion
    B_slide_current = 0
    while B_slide_current < B_slide_distance:
        pose_current = group.get_current_pose().pose
        pos_current = np.array((pose_current.position.x, pose_current.position.y, pose_current.position.z))
        translation_current = np.linalg.norm(pos_current - pos_initial)
        gripper_offset_current = gripper_offset/translation_final*translation_current
        # print translation_current, translation_current**2 - gripper_offset_current**2
        B_slide_current = translation_current #temp 
        #close gripper pos according to object geometry
        close_width = width - (math.tan(math.radians(psi_regrasp)) * B_slide_current) * 0.75 #tune for the finger contacting with the object
        Robotiq.goto(robotiq_client, pos=close_width+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False)
        rospy.sleep(0.1)

def generalized_release(axis, psi_regrasp, A_slide_dist, velocity, psi_0=0):
    '''Generalized release primitive motion (hybird motion of regrasp and sliding)

    Parameters:
        axis (list): 3-D vector of rotation axis (right-hand rule)
        psi_regrasp (double): angle to regrasp
        A_slide_dist (double): distance to slide at contact A
        velocity (double): robot velocity between 0 and 1
        psi_0 (double): psi angle before executing this primitive
    '''

    tcp2fingertip = gbs.config['tcp2fingertip']
    theta_0 = gbs.config['theta_0']
    delta_0 = gbs.config['delta_0']
    obj_thickness = gbs.config['object_thickness']

    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)

    #contact A position in world coordinate
    pose_target = group.get_current_pose().pose
    pos_initial = [pose_target.position.x, pose_target.position.y, pose_target.position.z]
    ori_initial = [pose_target.orientation.x, pose_target.orientation.y, pose_target.orientation.z, pose_target.orientation.w]
    T_we = tf.TransformListener().fromTranslationRotation(pos_initial, ori_initial) 
    contact_A_e = [tcp2fingertip, gbs.config['object_thickness']/2, 0, 1] #TODO: depends on axis direction 
    contact_A_w = np.matmul(T_we, contact_A_e) 

    #compute robot path
    A_slide_hori = A_slide_dist * math.cos(math.radians(theta_0))
    A_slide_verti = A_slide_dist * math.sin(math.radians(theta_0))
    if psi_regrasp > 0:
        # Interpolate orientation poses via quaternion slerp
        q = helper.axis_angle2quaternion(axis, psi_regrasp)
        ori_target = tf.transformations.quaternion_multiply(q, ori_initial)    
        ori_waypoints = helper.slerp(ori_initial, ori_target, np.arange(1.0/psi_regrasp , 1.0+1.0/psi_regrasp, 1.0/psi_regrasp)) 
        waypoints = []
        for psi in range(1, psi_regrasp+1):
            # Calculate gripper width
            a = (delta_0 - A_slide_dist*psi/psi_regrasp) * math.cos(math.radians(psi))
            b = (delta_0 - A_slide_dist*psi/psi_regrasp) * math.sin(math.radians(psi))
            c = obj_thickness * math.cos(math.radians(psi))
            d = obj_thickness * math.sin(math.radians(psi))
            opposite = a - d
            width = b + c

            # Calculate distance from A to tcp
            if theta_0 + psi <= 90:
                hori =  math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi)))
                verti =  math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi))) - math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi)))
            else:
                hori = -math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.cos(math.radians(theta_0+psi-90)))
                verti = math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 + psi-90))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0+psi-90)))

            if axis[0] > 0:
                pose_target.position.y = contact_A_w[1] + hori + A_slide_hori * psi/psi_regrasp
                pose_target.position.z = contact_A_w[2] + verti + A_slide_verti * psi/psi_regrasp
                #print "CASE 1"
            elif axis[0] < 0:
                pose_target.position.y = contact_A_w[1] - hori - A_slide_hori * psi/psi_regrasp
                pose_target.position.z = contact_A_w[2] + verti + A_slide_verti * psi/psi_regrasp
                #print "CASE 2"
            elif axis[1] > 0:
                pose_target.position.x = contact_A_w[0] - hori - A_slide_hori * psi/psi_regrasp
                pose_target.position.z = contact_A_w[2] + verti + A_slide_verti * psi/psi_regrasp
                #print "CASE 3"
            elif axis[1] < 0:
                pose_target.position.x = contact_A_w[0] + hori + A_slide_hori * psi/psi_regrasp
                pose_target.position.z = contact_A_w[2] + verti + A_slide_verti * psi/psi_regrasp
                #print "CASE 4"

            pose_target.orientation.x = ori_waypoints[psi-1][0]
            pose_target.orientation.y = ori_waypoints[psi-1][1]
            pose_target.orientation.z = ori_waypoints[psi-1][2]
            pose_target.orientation.w = ori_waypoints[psi-1][3]
            waypoints.append(copy.deepcopy(pose_target))
        (plan, fraction) = group.compute_cartesian_path(waypoints, 0.01, 0) 
        retimed_plan = group.retime_trajectory(robot.get_current_state(), plan, velocity) 
        group.execute(retimed_plan, wait=False)
    else: #for the case: psi_regrasp = 0
        if axis[0] > 0:
            motion_primitives.linear_path([0, A_slide_hori, A_slide_verti], velocity, False)
        elif axis[0] < 0:
            motion_primitives.linear_path([0, -A_slide_hori, A_slide_verti], velocity, False)
        elif axis[1] > 0:
            motion_primitives.linear_path([-A_slide_hori, 0, A_slide_verti], velocity, False)
        elif axis[1] < 0:
            motion_primitives.linear_path([A_slide_hori, 0, A_slide_verti], velocity, False)

    #gripper motion
    if psi_regrasp > 0:
        psi = 0
        width_max = 0
        width_const = 0.85 #const for opening
        while psi < psi_regrasp:
            pose = group.get_current_pose().pose
            q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
            #get current psi angle
            psi = 2*math.degrees(math.acos(np.dot(q_current, ori_initial))) 
            if psi > 100:
                psi = -(psi-360)
            #get current delta
            delta_change = A_slide_dist*psi/psi_regrasp #math.sqrt((A_slide_hori * psi/psi_regrasp)**2 + (A_slide_verti * psi/psi_regrasp)**2)
            delta = delta_0 - delta_change
            a = delta * math.cos(math.radians(psi))
            b = delta * math.sin(math.radians(psi))
            c = obj_thickness * math.cos(math.radians(psi))
            d = obj_thickness * math.sin(math.radians(psi))
            opposite = a - d
            width = b + c
            if width > width_max:
                width_max = width
            else:
                width_const = 1.0 #const for closing
            print psi, delta_change, width #debug
            Robotiq.goto(robotiq_client, pos=width*width_const+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #TODO: tune the constant for width
            enable_palm = 1
            if enable_palm:
                palm_position = 98 + 1.08*(gbs.config['delta_0'] - a)*1000 #100,1.2
                dynamixel.set_length(palm_position)
            psi = round(psi, 2)
            rospy.sleep(0.5) 
    else: #for the case: psi_regrasp = 0
        slide_current = 0
        while slide_current < A_slide_dist:
            pose_current = group.get_current_pose().pose
            pos_current = np.array((pose_current.position.x, pose_current.position.y, pose_current.position.z))
            slide_current = np.linalg.norm(pos_current - pos_initial)
            delta = delta_0 - slide_current #current delta
            # print delta, slide_current #debug
            width = delta * math.sin(math.radians(psi_0)) + obj_thickness * math.cos(math.radians(psi_0))
            Robotiq.goto(robotiq_client, pos=width+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False)
            rospy.sleep(0.5)

    return width

def combine_release(point, axis, theta_tilt, psi_regrasp, A_slide_dist, velocity, psi_0=0):
    #Not yet tested!
    #axis: tilt_axis
    #TODO: shift center during regrasp: done by tilting contact A position
    #combine theta and psi rotation, done
    #gripper motion
    #consider previous theta, psi, delta value

    tcp2fingertip = gbs.config['tcp2fingertip']
    theta_0 = gbs.config['theta_0']
    delta_0 = gbs.config['delta_0']
    obj_thickness = gbs.config['object_thickness']

    action_name = rospy.get_param('~action_name', 'command_robotiq_action')
    robotiq_client = actionlib.SimpleActionClient(action_name, CommandRobotiqGripperAction)

    # Normalize axis vector
    axis = axis/np.linalg.norm(axis)
    axis_regrasp = np.multiply(axis,-1)

    #get current pose
    pose_target = group.get_current_pose().pose
    pos_initial = [pose_target.position.x, pose_target.position.y, pose_target.position.z]
    ori_initial = [pose_target.orientation.x, pose_target.orientation.y, pose_target.orientation.z, pose_target.orientation.w]

    # Tilt center point. Closest point from tcp to axis line    
    center = np.add(point, np.dot(np.subtract(pos_initial, point), axis)*axis)
    # Closest distance from tcp to axis line
    radius = np.linalg.norm(np.subtract(center, pos_initial))
    # Pair of orthogonal vectors in tilt plane
    v1 =  -np.subtract(np.add(center, np.dot(np.subtract(pos_initial, center), axis)*axis), pos_initial)
    v1 = v1/np.linalg.norm(v1)
    v2 = np.cross(axis, v1)

    #contact A position
    T_we = tf.TransformListener().fromTranslationRotation(pos_initial, ori_initial) 
    contact_A_e = [tcp2fingertip, gbs.config['object_thickness']/2, 0, 1] #TODO: depends on axis direction 
    contact_A_w = np.matmul(T_we, contact_A_e) 

    #interpolate the rotation of tilt and regrasp
    #equaling the their interpolated steps with the larger one
    angle_combine = theta_tilt - psi_regrasp
    if theta_tilt > psi_regrasp:
        stepRatio_tilt = 1
        stepRatio_regrasp = psi_regrasp/theta_tilt
        stepRatio_combine = angle_combine/theta_tilt
        steps = theta_tilt
    else: 
        stepRatio_tilt = theta_tilt/psi_regrasp
        stepRatio_regrasp = 1
        stepRatio_combine = angle_combine/psi_regrasp
        steps = psi_regrasp
    #interpolate tilt rotation
    q_tilt = helper.axis_angle2quaternion(axis, theta_tilt)
    ori_target_tilt = tf.transformations.quaternion_multiply(q_tilt, ori_initial)    
    ori_waypoints_tilt = helper.slerp(ori_initial, ori_target_tilt, np.arange(1.0/theta_tilt , 1.0+1.0/theta_tilt, 1.0/theta_tilt*stepRatio_tilt))
    #interpolate regrasp rotation
    q_regrasp = helper.axis_angle2quaternion(axis_regrasp, psi_regrasp)
    ori_target_regrasp = tf.transformations.quaternion_multiply(q_regrasp, ori_initial)    
    ori_waypoints_regrasp = helper.slerp(ori_initial, ori_target_regrasp, np.arange(1.0/psi_regrasp , 1.0+1.0/psi_regrasp, 1.0/psi_regrasp*stepRatio_regrasp))
    #combined rotation
    q_combine = helper.axis_angle2quaternion(axis, angle_combine)
    ori_target_combine = tf.transformations.quaternion_multiply(q_combine, ori_initial)    
    ori_waypoints_combine = helper.slerp(ori_initial, ori_target_combine, np.arange(1.0/angle_combine , 1.0+1.0/angle_combine, 1.0/angle_combine*stepRatio_combine))
    print len(ori_waypoints_tilt), len(ori_waypoints_regrasp), len(ori_waypoints_combine) #check their leng if the same

    waypoints = []
    for i in range(1, steps+1):
        #get theta and psi from quaternion
        theta = 2*math.degrees(math.acos(ori_waypoints_tilt[i-1][3]))
        psi = 2*math.degrees(math.acos(ori_waypoints_regrasp[i-1][3]))
        #trajactory of tcp during tilt
        circle = np.add(center, radius*(math.cos(math.radians(theta)))*v1 + radius*(math.sin(math.radians(theta)))*v2)
        #calculate A slide component in hori, verti axis 
        A_slide_hori = A_slide_dist * math.cos(math.radians(theta_0 - theta))
        A_slide_verti = A_slide_dist * math.sin(math.radians(theta_0 - theta))
        # Calculate gripper width
        a = (delta_0 - A_slide_dist*i/steps) * math.cos(math.radians(psi))
        b = (delta_0 - A_slide_dist*i/steps) * math.sin(math.radians(psi))
        c = obj_thickness * math.cos(math.radians(psi))
        d = obj_thickness * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c
        #calculate distance from A to tcp 
        if theta_0 + psi <= 90:
            hori =  math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 - theta + psi))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0 - theta + psi)))
            verti =  math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 - theta + psi))) - math.fabs((width/2.0)*math.cos(math.radians(theta_0 - theta + psi)))
        else:
            hori = -math.fabs(tcp2fingertip*math.sin(math.radians(theta_0 - theta + psi-90))) + math.fabs((width/2.0)*math.cos(math.radians(theta_0 - theta + psi-90)))
            verti = math.fabs(tcp2fingertip*math.cos(math.radians(theta_0 - theta + psi-90))) + math.fabs((width/2.0)*math.sin(math.radians(theta_0 - theta + psi-90)))
        #contact A relative to G
        contact_A_G = np.subtract(contact_A_w, point)
        if axis_regrasp[0] > 0:
            #tilted contact_A 
            contact_A_t_hori = contact_A_G[1]*math.cos(math.radians(theta)) + contact_A_w[2]*math.sin(math.radians(theta)) + point[1]
            contact_A_t_verti =  -contact_A_G[1]*math.sin(math.radians(theta)) + contact_A_w[2]*math.cos(math.radians(theta)) + point[2]
            pose_target.position.y = contact_A_t_hori + hori + A_slide_hori * i/steps
            pose_target.position.z = contact_A_t_verti + verti + A_slide_verti * i/steps
            #print "CASE 1"
        elif axis_regrasp[0] < 0:
            #tilted contact_A 
            contact_A_t_hori = contact_A_G[1]*math.cos(math.radians(theta)) + contact_A_w[2]*math.sin(math.radians(theta)) + point[1]
            contact_A_t_verti =  -contact_A_G[1]*math.sin(math.radians(theta)) + contact_A_w[2]*math.cos(math.radians(theta)) + point[2]
            pose_target.position.y = contact_A_t_hori - hori - A_slide_hori * i/steps
            pose_target.position.z = contact_A_t_verti + verti + A_slide_verti * i/steps
            #print "CASE 2"
        elif axis_regrasp[1] > 0:
            pose_target.position.x = contact_A_w[0] - hori - A_slide_hori * i/steps
            pose_target.position.z = contact_A_w[2] + verti + A_slide_verti * i/steps
            #print "CASE 3"
        elif axis_regrasp[1] < 0:
            pose_target.position.x = contact_A_w[0] + hori + A_slide_hori * i/steps
            pose_target.position.z = contact_A_w[2] + verti + A_slide_verti * i/steps
            #print "CASE 4"

        pose_target.orientation.x = ori_waypoints_combine[i-1][0]
        pose_target.orientation.y = ori_waypoints_combine[i-1][1]
        pose_target.orientation.z = ori_waypoints_combine[i-1][2]
        pose_target.orientation.w = ori_waypoints_combine[i-1][3]
        waypoints.append(copy.deepcopy(pose_target))
    (plan, fraction) = group.compute_cartesian_path(waypoints, 0.01, 0) 
    retimed_plan = group.retime_trajectory(robot.get_current_state(), plan, velocity) 
    group.execute(retimed_plan, wait=False)
        
    #gripper motion
    psi = 0
    while psi < psi_regrasp:
        pose = group.get_current_pose().pose
        q_current = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]
        angle_current = 2*math.degrees(math.acos(np.dot(q_current, ori_initial)))
        #get current value based on the steps the robot executed
        current_step = steps*angle_current/angle_combine
        if current_step > steps:
            current_step = steps
        #get current psi
        psi = 2*math.degrees(math.acos(ori_waypoints_regrasp[curret_step][3]))
        #get current delta
        delta_change = A_slide_dist*psi/psi_regrasp
        delta = delta_0 - delta_change
        a = delta * math.cos(math.radians(psi))
        b = delta * math.sin(math.radians(psi))
        c = obj_thickness * math.cos(math.radians(psi))
        d = obj_thickness * math.sin(math.radians(psi))
        opposite = a - d
        width = b + c
        print psi, delta_change, width #debug
        Robotiq.goto(robotiq_client, pos=width*1.08+gbs.config['gripper_offset'], speed=gbs.config['gripper_speed'], force=gbs.config['gripper_force'], block=False) #TODO: tune the constant for width
        psi = round(psi, 2)
        rospy.sleep(0.5) 




if __name__ == '__main__':
    try:
        rospy.init_node('regrasp', anonymous=True)  
        group.set_max_velocity_scaling_factor(1.0)
        motion_primitives.set_joint([0, -90, 90, 90, 90, 0])  
        p = group.get_current_pose().pose 
        tilt.tilt([p.position.x,p.position.y,p.position.z-0.275], [0,-1,0], 60, 0.5)
        regrasp([0,1,0], 90, 0.1)
        
    except rospy.ROSInterruptException: pass
