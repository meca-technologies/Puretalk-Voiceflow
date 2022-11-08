# Puretalk-Voiceflow
## Diagrams
### Twilio Layout
![Twilio Overview](https://dashboard.puretalk.ai/static/img/diagram_vf.jpg)
### Stack Layout
![Twilio Overview](https://dashboard.puretalk.ai/static/img/stack-vf-sm.jpg)
## Definitions
### NGINX
NGINX, is an open-source web server that is also used as a reverse proxy, HTTP cache, and load balancer.
### GUNICORN
Green Unicorn (Gunicorn) is a Python WSGI server that runs Python web application code. Gunicorn is one of many WSGI server implementations, but it’s particularly important because it is a stable, commonly-used part of web app deployments that’s powered some of the largest Python-powered web applications , such as Instagram
### HOW NGINX, GUNICORN, and FLASK work together
Nginx is at the outermost tier of the Backend(3-tiers). Middle tier is the Gunicorn and third tier is the python app which ultimately connects to the database.
Nginx is used as proxy, reverse proxy, load balancer, static data dispatcher and cache etc. While Gunicorn is the Interface between the nginx server and the python app so that the app(or any python framework) understands the incoming requests and process them accordingly.
## How it works
1. First a call is triggered by the campaign manager. When the call is created a status callback webhook is established which includes the voiceflow api token.
2. When the call is connected/answered we trigger a conversation with voiceflow with an id which is associated with the twilio CallSID and a first response with the text "Hello" for voiceflow to receive. This is to start the conversation and track the context of the conversation.
3. The "Hello" from the initial response triggers the greeting from Voiceflow. We iterate through the response from voiceflow to pull each of the speech responses.
4. We convert those speech responses into audio using the TTS conversion function. This creates a file with a md5 hashed title of the speech response. Before creating the file it checks to see if it has already given that response before so that it can cut down on response time.
5. Once the file is created we then format it into an XML response so that Twilio can play the file. This XML response also includes a status callback webhook so that we can continue the responses.
6. The customer can then speak to the AI which will converted to text for status callback webhook. This process continues until the customer hangs up, doesn't qualify, or the customer is transferred.
7. To transfer the customer the text "transfer-now" needs to be passed from voiceflow
## Installation
### NGINX Install
#### Installing NGINX
* Since Nginx is available in Ubuntu’s default repositories, it is possible to install it from these repositories using the apt packaging system. Since this may be your first interaction with the apt packaging system in this session, update the local package index so that you have access to the most recent package listings. Afterward, you can install nginx:
```bash
sudo apt update
sudo apt install nginx
```
#### Firewall Adjustment
* Before testing Nginx, the firewall software needs to be adjusted to allow access to the service. Nginx registers itself as a service with ufw upon installation, making it straightforward to allow Nginx access. It is recommended that you enable the most restrictive profile that will still allow the traffic you’ve configured. Since you haven’t configured SSL for your server yet in this guide, you’ll only need to allow traffic on port 80. You can enable this by typing the following:
```bash
sudo ufw allow 'Nginx HTTP'
```
* Verify the change
```bash
sudo ufw status
```
* Verify NGINX status
```bash
systemctl status nginx
```
### Flask with GUNICORN
#### Installing Components
* The first step is to install all of the necessary packages from the default Ubuntu repositories. This includes pip, the Python package manager, which will manage your Python components. You’ll also get the Python development files necessary to build some of the Gunicorn components. First, update the local package:
```bash
sudo apt update
```
* Then install the packages that will allow you to build your Python environment. These include python3-pip, along with a few more packages and development tools necessary for a robust programming environment:
```bash
sudo apt install python3-pip python3-dev build-essential libssl-dev libffi-dev python3-setuptools
```
* With these packages in place, move on to creating a virtual environment for your project.
#### Setting up Python Virtual Environment
* Next, set up a virtual environment to isolate your Flask application from the other Python files on the system. Start by installing the python3-venv package, which will install the venv module:
```bash
sudo apt install python3-venv
cd /var/www
mkdir voiceflow
cd voiceflow
```
* Create a virtual environment
```bash
python3 -m venv voiceflowenv
```
* Activate the source
```bash
source voiceflowenv/bin/activate
```
* Clone Repo
```bash
git clone https://github.com/meca-technologies/Puretalk-Voiceflow.git 
```
* Install all requirements
```bash
pip install -r requirements.txt
```
* You can test the webserver by running
```bash
gunicorn --bind 0.0.0.0:5005 wsgi:app
```
* Output should look like this
```
Output
[2021-11-19 23:07:57 +0000] [8760] [INFO] Starting gunicorn 20.1.0
[2021-11-19 23:07:57 +0000] [8760] [INFO] Listening at: http://0.0.0.0:5005 (8760)
[2021-11-19 23:07:57 +0000] [8760] [INFO] Using worker: sync
[2021-11-19 23:07:57 +0000] [8763] [INFO] Booting worker with pid: 8763
[2021-11-19 23:08:11 +0000] [8760] [INFO] Handling signal: int
[2021-11-19 23:08:11 +0000] [8760] [INFO] Shutting down: Master
```
#### Setting up GUNICORN
* Start by deactivating the virtual environment & it should work
```bash
deactivate
```
* Create a unit file ending in .service within the /etc/systemd/system directory to begin:
```bash
sudo nano /etc/systemd/system/voiceflow.service
```
* Inside paste the following and save the file:
```bash
[Unit]
Description=Gunicorn instance to serve puretalk dashboard
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/voiceflow
Environment="PATH=/var/www/voiceflow/voiceflowenv/bin"
ExecStart=/var/www/voiceflow/voiceflowenv/bin/gunicorn --workers 10 --bind unix:myproject.sock -m 007 wsgi:app

[Install]
WantedBy=multi-user.target
```
* Now we can start the service
```bash
sudo systemctl start voiceflow
```
* Then enable it so that it starts at boot:
```bash
sudo systemctl enable voiceflow
```
* Check the status:
```bash
sudo systemctl status voiceflow
```
* The output for above should be similar to this
```bash
● voiceflow.service - Gunicorn instance to serve myproject
   Loaded: loaded (/etc/systemd/system/voiceflow.service; enabled; vendor preset
   Active: active (running) since Fri 2021-11-19 23:08:44 UTC; 6s ago
 Main PID: 8770 (gunicorn)
    Tasks: 10 (limit: 1151)
   CGroup: /system.slice/voiceflow.service
       	├─9291 /var/www/voiceflow/voiceflowenv/bin/python3.6 /var/www/voiceflow/voiceflowenv/bin/gunicorn --workers 3 --bind unix:voiceflow.sock -m 007 wsgi:app
       	├─9309 /var/www/voiceflow/voiceflowenv/bin/python3.6 /var/www/voiceflow/voiceflowenv/bin/gunicorn --workers 3 --bind unix:voiceflow.sock -m 007 wsgi:app
       	├─9310 /var/www/voiceflow/voiceflowenv/bin/python3.6 /var/www/voiceflow/voiceflowenv/bin/gunicorn --workers 3 --bind unix:voiceflow.sock -m 007 wsgi:app
       	└─9311 /var/www/voiceflow/voiceflowenv/bin/python3.6 /var/www/voiceflow/voiceflowenv/bin/gunicorn --workers 3 --bind unix:voiceflow.sock -m 007 wsgi:app
…
```
#### Configuring NGINX
* Begin by creating a new server block configuration file in Nginx’s sites-available directory. We’ll call this voiceflow to stay consistent with the rest of the guide:
```bash
sudo nano /etc/nginx/sites-available/voiceflow
```
* Paste:
```bash
server {
    listen 80;
    server_name voiceflow.puretalk.ai www.voiceflow.puretalk.ai;

    client_max_body_size 100M;

    proxy_headers_hash_max_size 512;
    proxy_headers_hash_bucket_size 128;

    location / {
        include proxy_params;
        proxy_set_header        X-Real-IP         $remote_addr;
        proxy_set_header        X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_pass http://unix:/var/www/voiceflow/voiceflow.sock;
    }
}
```
* To enable the Nginx server block configuration you’ve created, link the file to the sites-enabled directory. You can do this by running the ln command and the -s flag to create a symbolic or soft link, as opposed to a hard link:
```bash
sudo ln -s /etc/nginx/sites-available/voiceflow /etc/nginx/sites-enabled
```
* Test for syntax errors
```bash
sudo nginx -t
```
* If there are no issues restart NGINX
```bash
sudo systemctl restart nginx
```
* Allow full to the NGINX server:
```bash
sudo ufw allow 'Nginx Full'
```

### Commands
```bash
cd /var/www/voiceflow
source voiceflowenv/bin/activate
sudo systemctl start voiceflow.service
```
