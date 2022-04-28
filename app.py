from flask import Flask, request, Response, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client

import plivo

import pymongo
from bson.objectid import ObjectId
import logging

import datetime

import requests
import sqlite3
from config import DB_PATH, redis_password

import openai
import redis
import hashlib
import os
from sqlescapy import sqlescape

tts_url = 'http://137.184.57.49:5006/convert'

xfer_response = ['transfer-now']

# setting up logging
logger = logging.getLogger('Voiceflow')
logger.setLevel(logging.DEBUG)
todayFormatted = (datetime.datetime.today()).strftime("%Y-%m-%d")
fh = logging.FileHandler('logs/voiceflow-{}.py.log'.format(todayFormatted))
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("[%(asctime)s] - %(name)14s - %(levelname)8s | %(message)s","%Y-%m-%d %H:%M:%S")
fh.setFormatter(formatter)
logger.addHandler(fh)


app = Flask(__name__)
app.secret_key = '2abceVR5ENE7FgMxXdMwuzUJKC2g8xgy'

app.redis = redis.Redis(
    host='161.35.14.195',
    port=6379,
    password=redis_password)

app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True
app.mongo_client = pymongo.MongoClient("mongodb+srv://admin:QM6icvpQ6SlOveul@cluster0.vc0rw.mongodb.net/myFirstDatabase?retryWrites=true&w=majority")

@app.route('/record/<api_key>', methods=['POST'])
def recordCall(api_key):
    call_id = request.form.get("CallUUID")
    logger.debug(call_id)
    action_url = f"https://voiceflow.puretalk.ai/VF.DM.61eafd218f8500001ba1965f.G1tLeNLTWDF3vuEm?active=1"

    voice_response_xml = f'''<Response>    
    <Record startOnDialAnswer="true" redirect="false" />
    <GetInput action="{action_url}" inputType="speech" />
    </Response>'''
    return Response(str(voice_response_xml), mimetype="text/xml")

### THIS ROUTE HANDLES ALL OF THE VOICE ACTION WEBHOOKS SENT FROM TWILIO
### THE SLUG IS THE VF API KEY FOR THE BOT
### REQUEST PARAMS HANDLES WHETHER IT IS USING ACTIVE LISTENING AND WHETHER IT IS USING THE SANDBOX MODULE
### REQUEST FORM HANDLES THE FOLLOWING
###     - CALLSID: THE UNIQUE ID FOR THE CALL FROM TWILIO. ALSO USED AS THE CONVERSATION ID IN VOICEFLOW
###     - SPEECHRESULT: THIS IS THE TEXT CONVERTED FROM SPEECH OF THE CUSTOMER
###     - FROM/TO: DEPENDING ON THE DIRECTION OF THE CALL THIS IS THE CUSTOMER PHONE NUMBER. THIS IS USED AS THE XFER CALLER ID 
###     - DIRECTION: WHETHER THE CALL WAS OUTBOUND OR INBOUND 
@app.route('/<api_key>', methods=['POST'])
def index(api_key):
    sandbox = False
    hangup = False
    audio_files = []
    if request.args.get('sandbox') == '1':
        sandbox = True
    logger.debug(str(request.form))
    call_id = request.form.get("CallSid")
    if call_id == None:
        call_id = request.form.get("CallUUID")
    text = request.form.get("SpeechResult")
    if text == None:
        text = request.form.get("Speech")
    if text:
        text = cleanText(text)
    logger.debug('Twilio Speech Result: {}'.format(text))
    logger.debug(text)

    # TWILIO VOICE RESPONSE BUILDER *ONLY FOR NON-ACTIVE LISTENING
    voice_response = VoiceResponse()

    # THIS THE URL WE CALLBACK TO WHEN THE CUSTOMER TALKS AGAIN
    action_url = f"https://voiceflow.puretalk.ai/{api_key}"

    if sandbox:
        action_url += '?sandbox=1'
        if request.args.get('active') == '1':
            action_url += '&active=1'

    if request.args.get('active') == '1':
        action_url += '?active=1'

    # TWILIO VOICE RESPONSE BUILDER *ONLY FOR ACTIVE LISTENING
    voice_response_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="{action_url}" actionOnEmptyResult="true" enhanced="true" input="speech" speechModel="phone_call" speechTimeout="0">
    '''

    # PLIVO VOICE RESPONSE BUILDER *ONLY FOR PLIVO
    voice_response_xml_plivo = f'''<Response>
    <GetInput action="{action_url}" inputType="speech">
    '''

    # NON ACTIVE LISTENING GATHER
    gather = Gather(
        input="speech",
        action=action_url,
        actionOnEmptyResult=True,
        speechTimeout=0,
        speechModel='phone_call',
        enhanced=True,
    )
    transfer = False
    first_time = True
    try:
        # THERE WAS NO SPEECH CHECK TO SEE IF THE CALL IS NEW OR NOT
        if text == None: 
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            logger.debug(f"SELECT * FROM calls WHERE call_id = '{call_id}'")
            for row in cur.execute(f"SELECT * FROM calls WHERE call_id = '{call_id}'"):
                first_time = False
            con.close()
            if first_time:
                text = 'Hello'
        else:
            first_time = False
        # THERE WAS A SPEECH FROM THE CUSTOMER
        if text:
            if sandbox:
                updateSandboxConversation(call_id, "client", text)
            # CREATE A RECORD OF THE CALL SINCE IT IS NEW
            if first_time:
                logger.debug('First time need to create record')
                updateSQL(f"insert into calls(call_id, transfer, hangup, repeat_times, repeat_text) values('{call_id}', 0, 0, 0, '')")
            
            # GENERATE JSON BODY FOR VOICEFLOW WITH WHAT THE CUSTOMER RESPONDED WITH
            body = {"request": {"type": "text", "payload": text}}

            # START/CONTINUE CONVERSATION
            # SEND THE CUSTOMER RESPONSE TO VOICEFLOW
            logger.debug('Making Request to voiceflow')
            response = requests.post(
                f"https://general-runtime.voiceflow.com/state/user/{call_id}/interact",
                json=body,
                headers={"Authorization": api_key},
            )
            req_json = response.json()
            logger.debug(req_json)
            first_text_line = True
            logger.debug('Voiceflow JSON: {}'.format(str(req_json)))
            
            # GO THROUGH VOICEFLOW API RESPONSE AND GET AI RESPONSE
            for response in req_json:
                # CHECK FOR AN AI RESPONSE
                has_message = False
                try:
                    if response['payload']['message']:
                        has_message = True
                except:
                    pass
                # THERE IS A RESPONSE FROM THE AI
                if has_message:
                    # CREATES/RETRIEVES TTS AUDIO FOR AI RESPONSE
                    msg_text = response['payload']['message']
                    play_file = createFile(msg_text)
                    logger.debug(f'PLAY FILE: {play_file}')
                    
                    # UPDATES SANDBOX CONVERSATION
                    if sandbox:
                        updateSandboxConversation(call_id, "ai", msg_text)

                    logger.debug('AI Message: {}'.format(str(msg_text)))
                    con = sqlite3.connect(DB_PATH)
                    cur = con.cursor()
                    # CHECKS TO SEE IF WE ARE REPEATING OURSELVES
                    if first_text_line:
                        query = f"SELECT repeat_times FROM calls WHERE call_id = '{call_id}' and repeat_text = '%s'" % sqlescape(msg_text)
                        logger.debug(query)
                        logger.debug('UPDATE ROWS SQLITE: {}'.format(query))
                        repeat_times = 0

                        # SEE IF WE DID REPEAT OURSELVES
                        for row in cur.execute(query):
                            repeat_times = row[0]
                            repeat_times += 1
                            updateSQL(f"update calls set repeat_times = {repeat_times} where call_id = '{call_id}'")

                            # REPEATED OURSELVES TOO MANY TIMES SEND A HANGUP RESPONSE TO TWILIO
                            if repeat_times > 2:
                                try:
                                    updateNoAnswer(call_id)
                                except:
                                    pass
                                voice_response.hangup()
                                hangup = True
                        logger.debug(f'REPEATED TIMES: {repeat_times}')

                        # DIDN'T REPEAT OURSELVES SET IT BACK TO ZERO
                        if repeat_times == 0:
                            updateSQL(f"update calls set repeat_times = {repeat_times} where call_id = '%s'" % sqlescape(call_id))
                    first_text_line = False

                    # SET THE LAST THING THE CUSTOMER SAID
                    query = f"update calls set repeat_text = '%s' where call_id = '{call_id}'" % sqlescape(msg_text)
                    logger.debug(query)
                    logger.debug('UPDATE CALLS SQLITE: {}'.format(query))
                    updateSQL(query)
                    logger.debug('COMMITTED UPDATE CALLS SQLITE')

                    # CHECK TO SEE IF WE NEED TO TRANSFER THE CALL OR NOT
                    if not msg_text in xfer_response:
                        voice_response_xml += play_file
                        voice_response_xml_plivo += play_file
                        voice_response.play(cleanForNonActive(play_file))
                        audio_files.append(play_file)
                        logger.debug(f'AUDIO FILES: {audio_files}')
                    elif msg_text in xfer_response:
                        transfer = True
                        xfer_number = getCampaignXfer(call_id)
                        xfer_caller_id = request.form.get("From")
                        if request.form.get("Direction") == 'outbound-api':
                            xfer_caller_id = request.form.get("To")
                        voice_response.dial(number=xfer_number, caller_id=xfer_caller_id)

                        voice_response_xml += f'''
                            <Dial callerId="{xfer_caller_id}" record="true" recordingStatusCallback="https://twilio.puretalk.ai/recording/callback" recordingStatusCallbackMethod="POST">
                                {xfer_number}
                            </Dial>
                        '''

                        voice_response_xml_plivo += f'''
                        <Dial>
                            <Number>+12392208726</Number>
                        </Dial>
                        '''
                        try:
                            data = {
                                'CallSid': call_id
                            }
                            url = 'http://twilio.puretalk.ai/calls/interested'
                            requests.post(url, json=data)
                            logger.debug("sending transfer data")
                        except:
                            logger.debug("Failed sending transfer data")
                else:
                    try:
                        # CHECK TO SEE IF VF IS SENDING AN END CONVERSATION
                        if response['type'] == 'end' and transfer == False:
                            logger.debug("HANGUP CALL")
                            voice_response.hangup()
                            hangup = True
                    except:
                        pass
        else:
            # CUSTOMER SAID NOTHING SO THE AI WILL REPEAT ITSELF
            msg_text = 'None'
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            for row in cur.execute(f"SELECT repeat_times FROM calls WHERE call_id = '{call_id}'"):
                repeat_times = row[0]
                repeat_times += 1
                updateSQL(f"update calls set repeat_times = {repeat_times} where call_id = '{call_id}'")
                if repeat_times > 2:
                    updateNoAnswer(call_id)
                    voice_response.hangup()
                    hangup = True
            con.close()
            
            body = {"request": {"type": "text", "payload": text}}

            # Start a conversation
            response = requests.post(
                f"https://general-runtime.voiceflow.com/state/user/{call_id}/interact",
                json=body,
                headers={"Authorization": api_key},
            )
            req_json = response.json()
            for response in req_json:
                has_message = False
                try:
                    if response['payload']['message']:
                        has_message = True
                except:
                    pass
                if has_message:
                    msg_text = response['payload']['message']
                    play_file = createFile(msg_text)

                    voice_response_xml += play_file

                    voice_response_xml_plivo += play_file
                    voice_response.play(cleanForNonActive(play_file))
                    audio_files.append(play_file)

        if transfer == False:
            voice_response.append(gather)
    except:
        try:
            logger.debug('FAILED 1')
            updateNoAnswer(call_id)
        except:
            logger.debug('FAILED 2')
            pass
        voice_response.hangup()
        hangup = True
    voice_response_xml += '''
        </Gather>
    </Response>
    '''

    voice_response_xml_plivo += '''
        </GetInput>
    </Response>
    '''
    if hangup == True:
        voice_response_xml = '''<Response>
'''
        for audio in audio_files:
            voice_response_xml += f'''
                {audio}
            '''
        voice_response_xml += '''
    <Hangup reason="rejected" />
</Response>
        '''
    if request.args.get('active') == '1' and transfer == False:
        logger.debug(str(voice_response_xml))
        if request.args.get('plivo') == '1':
            return Response(str(voice_response_xml_plivo), mimetype="text/xml")
        return Response(str(voice_response_xml), mimetype="text/xml")
    else:
        return Response(str(voice_response), mimetype="text/xml")

@app.route('/unknown', methods=['POST'])
def unknownIntent():
    logger.debug('Hit unkown intent: {}'.format(str(request.form)))
    call_id = request.form.get('CallSid')
    last_utterance = request.form.get('last_utterance')
    last_ai_utterance = request.form.get('last_ai_utterance')
    confidence = request.form.get('confidence')
    mongoDB = app.mongo_client['jamesbon']
    leads_col = mongoDB['leads']
    search_query = {
        "call_logs.call_id":call_id
    }
    lead = leads_col.find_one(search_query)
    unknown_intents_col = mongoDB['unknown_intents']
    insert_query = {
        'campaign_id':lead['campaign_id'],
        'lead_id':lead['_id'],
        'call_id':call_id,
        'last_utterance':last_utterance,
        'last_ai_utterance':last_ai_utterance,
        'confidence':confidence,
        'checked':False,
        'created_at':str(datetime.datetime.utcnow())[:-7],
        'updated_at':str(datetime.datetime.utcnow())[:-7]
    }
    unknown_intents_col.insert_one(insert_query)

    return jsonify({'Message':'Success'})

@app.route('/customerinfo', methods=['POST'])
def retCustomer():
    try:
        call_id = request.form.get('CallSid')
        logger.debug(f'HIT CUSTOMER INFO: {call_id}')
        mongoDB = app.mongo_client['jamesbon']
        leads_col = mongoDB['leads']
        search_query = {
            "call_logs.call_id":call_id
        }
        logger.debug(f'HIT CUSTOMER QUERY: {search_query}')
        lead = leads_col.find_one(search_query)
        logger.debug(f'HIT CUSTOMER VALUE: {lead}')
        return_post = {}
        for data in lead['lead_data']:
            field_name = data['field_name']
            field_name = field_name.replace(' ', '_')
            return_post[field_name] = data['field_value']
        logger.debug(f'HIT CUSTOMER RETURN: {return_post}')
        return jsonify(return_post)
    except:
        jsonify({"Message":"Failure"})

@app.route('/transfer', methods=['POST'])
def transfer():
    return jsonify({'Message':'Success'})
    
#######################################################
####   ____  _____  ______ _   _            _____  ####
####  / __ \|  __ \|  ____| \ | |     /\   |_   _| ####
#### | |  | | |__) | |__  |  \| |    /  \    | |   ####
#### | |  | |  ___/|  __| | . ` |   / /\ \   | |   ####
#### | |__| | |    | |____| |\  |  / ____ \ _| |_  ####
####  \____/|_|    |______|_| \_| /_/    \_\_____| ####
#######################################################                                             
                                              

@app.route('/oos', methods=['POST'])
def getOutOfScope():
    #try:
    openai.api_key = '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'
    call_id = request.form['CallSid']
    text = ''
    if app.redis.get(call_id):
        text += ' '+(app.redis.get(call_id)).decode("utf-8") + '\nQ: ' + request.form['text']
    else:
        text = '''I am a highly intelligent question answering bot. If you ask me a question that is rooted in truth, I will give you the answer. If you ask me a question that is nonsense, trickery, or has no clear answer, I will respond with "I am sorry can you rephrase that?".

Q: What is Obamacare?
A: It is a health insurance program that provides coverage to millions of Americans.

Q: If you are on medicare or medicaid do I still qualify?
A: No, you would not qualify for assistance.

Q: Do you need to make less than $1500 to qualify for Obamacare?
A: Yes, you need to make less than $1500 to qualify for assistance.

Q: What if I already have medicare?
A: Then you would not qualify for further assistance.

Q: Would I qualify for Medicare if I did?
A: You would qualify.
'''
        text += '\nQ: ' + request.form['text']
    text += '\nA:'
    response = openai.Completion.create(
        engine="text-davinci-002",
        prompt=f"{text}",
        temperature=0,
        max_tokens=80,
        top_p=1,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        stop=["\n"]
    )
    print(response)
    response_final = {
        'text':response['choices'][0]['text']
    }
    text += response['choices'][0]['text'] + '\n'
    print(text)
    app.redis.set(call_id, text)
    return jsonify(response_final)
    #except:
    #    return jsonify({'Message':'Failure'})

##############################################
####  _____  _      _______      ______   ####
#### |  __ \| |    |_   _\ \    / / __ \  ####
#### | |__) | |      | |  \ \  / / |  | | ####
#### |  ___/| |      | |   \ \/ /| |  | | ####
#### | |    | |____ _| |_   \  / | |__| | ####
#### |_|    |______|_____|   \/   \____/  ####      
############################################## 

@app.route('/plivo/call_back', methods=['POST'])
def plivoCallback():
    voice_response_xml = ''
    call_id = request.form.get("CallUUID")
    mongoDB = app.mongo_client['conversation-flow']
    conversations_col = mongoDB['conversations']
    conversation = conversations_col.find_one({'call_id':call_id})

    scripts_col = mongoDB['templates']
    script = scripts_col.find_one()
    step = {}
    speeches = []
    input_speech = ''
    speaking = True
    if conversation:
        curr_step = script['script'][conversation['current_step']]
        step_type = curr_step['type']
        if step_type == 'input':
            input_speech = curr_step['value']
            dtmf = request.form.get("Digits")
            result = 'success'
            if dtmf != '123456':
                result = 'failure'
            #speeches.append(str(dtmf))
            req_step = curr_step['event'][result]['next_step']
            step = script['script'][req_step]
        else:
            next_step = script['script'][conversation['current_step']]['next_step']
            step = script['script'][next_step]
    else:
        insert_query = {
            "call_id":call_id,
            "current_step":script['script']['start']['next_step'],
            "prev_step":None
        }
        conversation = conversations_col.insert(insert_query)
        print(str(conversation))
        step = script['script'][insert_query['current_step']]
    step_type = step['type']
    if step_type == 'hangup':
        speaking = False
        voice_response_xml = '''<Response>
            <Hangup />
        </Response>'''
    next_step = ''
    while speaking:
        try:
            speeches.append(step['value'])
        except:
            pass
        try:
            next_step = step['next_step']
            step = script['script'][step['next_step']]
        except:
            pass
        if step['type'] == 'input':
            input_speech = step['value']
            speaking = False
            url = 'https://a7dc-12-206-86-26.ngrok.io/plivo/call_back'
            voice_response_xml = f'''<Response>
            '''
            for speech in speeches:
                print(speech)
                voice_response_xml += f'''
                    <Speak>{speech}</Speak>'''
            voice_response_xml += f'''
                <GetDigits retries="3" action="{url}" method="POST">
                    <Speak>{input_speech}</Speak>
                </GetDigits>
            </Response>'''
        elif step['type'] == 'hangup':
            speaking = False
            voice_response_xml = f'''<Response>
            '''
            for speech in speeches:
                print(speech)
                voice_response_xml += f'''
                        <Speak>{speech}</Speak>'''
            voice_response_xml += '''
                <Hangup />
            </Response>'''
    
    search_query = {
        '_id':conversation
    }
    update_query = {
        "$set":{
            "current_step":next_step
        }
    }
    conversations_col.update_one(search_query, update_query)
    return Response(str(voice_response_xml), mimetype="text/xml")

#######################################################################
####  ______ _    _ _   _  _____ _______ _____ ____  _   _  _____  ####
#### |  ____| |  | | \ | |/ ____|__   __|_   _/ __ \| \ | |/ ____| ####
#### | |__  | |  | |  \| | |       | |    | || |  | |  \| | (___   ####
#### |  __| | |  | | . ` | |       | |    | || |  | | . ` |\___ \  ####
#### | |    | |__| | |\  | |____   | |   _| || |__| | |\  |____) | ####
#### |_|     \____/|_| \_|\_____|  |_|  |_____\____/|_| \_|_____/  ####
#######################################################################                                                          

def createFile(text):
    url = 'http://137.184.57.49:5006/convert'
    content = text
    if len(content) <= 280:
        file_name = str(hashlib.md5(content.encode('utf-8')).hexdigest()) + '.wav'
        if not findFile('./static/audio/'+file_name):
            payload = {
                "region":"eastus",
                "text":content
            }
            req = requests.post(url, json=payload)
            with open('./static/audio/'+file_name, mode='bx') as f:
                f.write(req.content)

        return f'''<Play>https://voiceflow.puretalk.ai/static/audio/{file_name}</Play>'''

def findFile(name):
    return os.path.exists(name)

def updateSandboxConversation(call_id, owner, message):
    mongoDB = app.mongo_client['jamesbon']
    sandbox_conversations_col = mongoDB['sandbox_conversations']
    search_query = {
        'call_sid':call_id
    }
    update_query = {
        '$push':{
            'conversation':{
                "owner":owner,
                "message":message
            }
        }
    }
    sandbox_conversations_col.update_one(search_query, update_query)

def updateNoAnswer(call_id):
    mongoDB = app.mongo_client['jamesbon']
    leads_col = mongoDB['leads']

    # Update Lead as interested
    search_query = {
        "call_logs.call_id":call_id
    }
    update_query = {
        '$set':{
            'status':'no-answer'
        }
    }
    leads_col.update_one(search_query,update_query)

def getCampaignXfer(call_id):
    mongoDB = app.mongo_client['jamesbon']
    leads_col = mongoDB['leads']
    search_query = {
        "call_logs.call_id":call_id
    }
    lead = leads_col.find_one(search_query)
    campaigns_col = mongoDB['campaigns']
    campaign = campaigns_col.find_one({'_id':lead['campaign_id']})
    return campaign['did']

def updateSQL(query):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(query)
    con.commit()
    con.close()

def cleanForNonActive(play_file):
    play_file = play_file.replace('<Play>', '')
    play_file = play_file.replace('</Play>', '')
    return play_file

def cleanText(text):
    text = str(text).replace(',', '')
    text = str(text).replace('.', '')
    text = str(text).replace('!', '')
    return text

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5005)
