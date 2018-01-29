
import boto3
import sys
import time
import json
import re
import argparse
import hashlib

parser = argparse.ArgumentParser()
parser.add_argument('command', nargs=1, choices=['update', 'delete', 'reset', 'add'])
parser.add_argument('--roster') 
parser.add_argument('--user') 
parser.add_argument('--password') 
args = parser.parse_args()

if args.command[0] == 'delete' or args.command[0] == 'reset' :
    if args.user is None :
        print ("Error: user is required.")
        parser.print_help()
        exit(1)
elif args.command[0] == 'update' :
    if args.roster is None :
        print ('Error: roster file is required.')
        parser.print_help()
        exit(1)
elif args.command[0] == 'update' :
    if args.user is None or args.password is None :
        print ('Error: user and password are required.')
        parser.print_help()
        exit(1) 
        
iam = boto3.client('iam')
c9_1 = boto3.client('cloud9', region_name='us-west-2')
c9_2 = boto3.client('cloud9', region_name='us-east-2')

def get_c9(username) :
    global c9_1, c9_2
    h = hashlib.sha1()
    h.update(username.encode('utf-8'))
    d = h.digest()
    i = int.from_bytes(d, byteorder='little', signed=True)
    if i < 0 :
        return c9_1
    else:
        return c9_2
    
def main() :
    global iam, args

    if args.command[0] == 'update' : 
        with open(args.roster) as r :
            rosters = json.loads(r.read())

        roster_users = {}
        for user in rosters['cis15s18'] :
            login = gen_login('cis15', user)
            roster_users[login['login']] = login

        aws_users = iam.list_users(PathPrefix='/student/')

        roster_usernames = set(roster_users.keys())
        aws_usernames = set([ x['UserName'] for x in aws_users['Users'] ])

        to_add = roster_usernames - aws_usernames
        for user in to_add :
            add_user(user, roster_users[user]['password'])

        to_del = aws_usernames - roster_usernames
        for user in to_del :
            delete_user(user) 

    elif args.command[0] == 'reset' :
        answer = input('Really RESET user {} ALL DATA WILL BE LOST? [y,N]: '.format(args.user))
        if answer == 'y' or answer == 'Y' :
            user = iam.get_user(UserName=args.user)
            delete_cloud9(args.user, user['User']['Arn'])
            create_cloud9(args.user, user['User']['Arn'])
        else:
            print ('Exit with no change. Safe.')
            
    elif args.command[0] == 'delete' :
        if args.user == 'all' :
            answer = input('Really DELETE ALL USERS? [y,N]: ')
            if answer == 'y' or answer == 'Y' :
                aws_users = iam.list_users(PathPrefix='/student/')
                for username in [ x['UserName'] for x in aws_users['Users'] ] :
                    delete_user(username)
            else:
                print ('Exit with no change. Safe.')
        else:
            delete_user(args.user)

    elif args.command[0] == 'add' :
        add_user(args.user, args.password)
        
    else:
        print ('Error: unrecognized command.')
        parser.print_help()
        exit(1)
        
def extract_name( student ) :
    rval = dict()
    n = student['name'];
    comma = n.index(',');
    rval['family'] = n[0:comma]
    dot = n.find('.')
    if dot > 0:
        rval['given'] = n[comma+2:dot-2]
    else:
        rval['given'] = n[comma+2:]

    return rval

def gen_login(class_name, student) :
    rval = extract_name(student)
    m = re.search('^(cs|cis)(\d+).*$', class_name)
    classnumber = m.group(2)
    rval['login'] = rval['family'][0:3].lower() + rval['given'][0:3].lower() + classnumber
    rval['password'] = rval['given'][0:2] + rval['family'][0:2] + student['id'][-4:]
    return rval

def delete_cloud9(username, user_arn) :
    # Find any C9 instances.
    c9 = get_c9(username)
    envs = c9.list_environments()
    env_desc = c9.describe_environments(environmentIds=envs['environmentIds'])

    for env in env_desc['environments'] :
        if env['ownerArn'] == user_arn :
            print ('Deleting Cloud9 environment {} for {}'.format(env['id'], user_arn))
            c9.delete_environment(environmentId=env['id'])

def delete_user(username):
    global iam

    c9 = get_c9(username)
    
    # Check if the user exists.
    user = iam.get_user(UserName=username);

    delete_cloud9(username, user['User']['Arn'])
    
    print ('Deleting user {}'.format(user['User']['Arn']))
    iam.remove_user_from_group(UserName=username, GroupName='cis-15')
    iam.delete_login_profile(UserName=username)
    iam.delete_user(UserName=username)

def create_cloud9(username, user_arn) :
    c9 = get_c9(username)
    while True :
        try :        
            resp = c9.create_environment_ec2(name=username,
                                             description='Your cis-15 workspace',
                                             instanceType='t2.nano',
                                             automaticStopTimeMinutes=30,
                                             ownerArn=user_arn)
            print ('Created a Cloud9 console for', user_arn)
            break
        except Exception as e:
            print ('[WARN]: Received error:', e) 
            time.sleep(5)
            
    resp = c9.create_environment_membership(environmentId=resp['environmentId'],
                                     userArn='arn:aws:iam::957903271915:user/matera',
                                     permissions='read-write') 

def add_user(username, password):
    global iam

    c9 = get_c9(username)
    
    print ('Adding user', username) 
    iam.create_user(UserName=username, Path='/student/')
    iam.create_login_profile(UserName=username, Password=password)
    iam.add_user_to_group(GroupName='cis-15', UserName=username)
    user = boto3.resource('iam').User(username)

    w = iam.get_waiter('user_exists')
    w.wait(UserName=username)

    create_cloud9(username, user.arn) 
    
if __name__ == '__main__' :
    main()

