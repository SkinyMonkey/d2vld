import os
import json
import sys
import logging

import etcd

logging.basicConfig(level=logging.DEBUG)

etcd_hostname = 'etcd'
etcd_client = etcd.Client(host=etcd_hostname)

from docker import Client

client = Client(base_url='unix://var/run/docker.sock')
events = client.events(decode=True)

def get_container(message):
    container = message['Actor']['Attributes']
    id = message['id']
    container['Env'] = client.inspect_container(id)['Config']['Env']
    container['Id'] = id
    
    print(container)
    return container

def get_envvar(container, to_find):
    for envvar in container['Env']:
	envvar = envvar.split('=')
        if envvar[0] == to_find:
            return envvar[1]
    return None

def get_container_hostname(container):
    return container['name']

def create_backend(backend_name):
    key = '/vulcand/backends/%s/backend' % backend_name
    try:
        etcd_client.read(key)
        return True
    except etcd.EtcdKeyNotFound:
        value = '{"Type": "http"}' # FIXME : https
        etcd_client.write(key, value)
        logging.info('Created backend : %s' % key)
        return False

def create_frontend(backend_name, ROUTE):
    key = '/vulcand/frontends/%s/frontend' % backend_name
    try:
        etcd_client.read(key)
        return True
    except etcd.EtcdKeyNotFound:
        # NOTE : Route could be passed as a raw string.
        #        More flexible but not needed
        value = '{"Type": "http", "BackendId": "%s", "Route": "PathRegexp(`%s.*`)"}'\
                % (backend_name, ROUTE)
        etcd_client.write(key, value)
        logging.info('Created frontend : %s' % key)
        return False

def add_container(container):
    server_name = container.get('name')

    ROUTE = get_envvar(container, 'ROUTE')

    if not ROUTE:
        logging.info('No route found for container: ' + server_name)
        return

    backend_name = server_name
    create_backend(backend_name)

    HOSTNAME = get_container_hostname(container)
    PORT = get_envvar(container, 'PORT')
    ROUTE = get_envvar(container, 'ROUTE')

    if PORT:
	if not ROUTE:
           logging.error('No ROUTE envvar could be found for this container' + backend_name)

        key = '/vulcand/backends/%s/servers/%s' % (backend_name, server_name)
        value = '{"URL": "http://%s:%s"}' % (HOSTNAME, PORT)

        etcd_client.write(key, value)
        logging.info('Added server: %s = %s on route %s' % (key, value, ROUTE))
        create_frontend(backend_name, ROUTE)
    else:
        logging.error('No PORT ENVVAR could be found for this container' + backend_name)

def remove_container(container):
    server_name = container.get('name')

    key = '/vulcand/backends/%s/servers/%s' % (server_name, server_name)
    try:
        etcd_client.delete(key)
        logging.info('Removed server: %s' % key)

    	key = '/vulcand/frontends/%s/frontend' % server_name
	try:
            etcd_client.delete(key)
    	except etcd.EtcdKeyNotFound as e:
            logging.error(e)

    except etcd.EtcdKeyNotFound as e:
        logging.error(e)

def create_listener(name, protocol, address):
    key = '/vulcand/listeners/%s' % name
    try:
        etcd_client.read(key)
    except etcd.EtcdKeyNotFound:
        value = '{"Protocol":"%s", "Address":{"Network":"tcp", "Address":"%s"}}' % (protocol, address)
        etcd_client.write(key, value)

# FIXME : needed?
create_listener('http', 'http', "0.0.0.0:80")

for event in events:
  action = event['Action']

  if action == 'start':
     logging.info('Started')
     container = get_container(event);
     add_container(container)

  elif action == 'die':
     logging.info('Terminated')
     container = get_container(event);
     remove_container(container)


print('exited')
