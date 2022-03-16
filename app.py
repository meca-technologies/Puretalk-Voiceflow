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
from config import DB_PATH

xfer_response = ['autotransport/transfer-1', 'transfer/Transfer', 'solar/transfer-1', 'solar/transfer-1', 'u65/hold', 'town-hall/transfer-1']

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

@app.route('/<api_key>', methods=['POST'])
def index(api_key):
    sandbox = False
    hangup = False
    audio_files = []
    if request.args.get('sandbox'):
        sandbox = True
    logger.debug(str(request.form))
    call_id = request.form.get("CallUUID")
    text = request.form.get("Speech")
    if text:
        text = str(text).replace(',', '')
        text = str(text).replace('.', '')
        text = str(text).replace('!', '')
    logger.debug('Twilio Speech Result: {}'.format(text))
    logger.debug(text)
    voice_response = VoiceResponse()
    action_url = f"https://voiceflow.puretalk.ai/{api_key}"
    if sandbox:
        action_url += '?sandbox=1'
        if request.args.get('active') == '1':
            action_url += '&active=1'

    if request.args.get('active') == '1':
        action_url += '?active=1'

    voice_response_xml = f'''<Response>
    <GetInput action="{action_url}" inputType="speech">
    '''
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
        
        if text:
            if sandbox:
                mongoDB = app.mongo_client['jamesbon']
                sandbox_conversations_col = mongoDB['sandbox_conversations']
                search_query = {
                    'call_sid':call_id
                }
                update_query = {
                    '$push':{
                        'conversation':{
                            "owner":"client",
                            "message":text
                        }
                    }
                }
                sandbox_conversations_col.update_one(search_query, update_query)
            if first_time:
                logger.debug('First time need to create record')
                con = sqlite3.connect(DB_PATH)
                cur = con.cursor()
                cur.execute(f"insert into calls(call_id, transfer, hangup, repeat_times, repeat_text) values('{call_id}', 0, 0, 0, '')")
                con.commit()
                con.close()
            body = {"request": {"type": "text", "payload": text}}

            # Start a conversation
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
            for response in req_json:
                has_message = False
                try:
                    if response['payload']['message']:
                        has_message = True
                except:
                    pass
                if has_message:
                    msg_text = response['payload']['message']
                    if sandbox:
                        mongoDB = app.mongo_client['jamesbon']
                        sandbox_conversations_col = mongoDB['sandbox_conversations']
                        search_query = {
                            'call_sid':call_id
                        }
                        update_query = {
                            '$push':{
                                'conversation':{
                                    "owner":"ai",
                                    "message":msg_text
                                }
                            }
                        }
                        sandbox_conversations_col.update_one(search_query, update_query)
                    logger.debug('AI Message: {}'.format(str(msg_text)))
                    con = sqlite3.connect(DB_PATH)
                    cur = con.cursor()
                    if first_text_line:
                        repeat_times = 0
                        for row in cur.execute(f"SELECT repeat_times FROM calls WHERE call_id = '{call_id}' and repeat_text = '{msg_text}'"):
                            repeat_times = row[0]
                            repeat_times += 1
                            cur.execute(f"update calls set repeat_times = {repeat_times} where call_id = '{call_id}'")
                            con.commit()
                            if repeat_times > 2:
                                try:
                                    
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
                                except:
                                    pass
                                voice_response.hangup()
                                hangup = True
                        if repeat_times == 0:
                            cur.execute(f"update calls set repeat_times = {repeat_times} where call_id = '{call_id}'")
                            con.commit()
                    first_text_line = False
                    cur.execute(f"update calls set repeat_text = '{msg_text}' where call_id = '{call_id}'")
                    con.commit()
                    con.close()

                    voice_response_xml += f'''
                    <Play>https://obama-care.s3.amazonaws.com/{msg_text}.mp3</Play>
                    '''
                    voice_response.play(f"https://obama-care.s3.amazonaws.com/{msg_text}.mp3")
                    audio_files.append(f"https://obama-care.s3.amazonaws.com/{msg_text}.mp3")
                    #voice_response.say(msg_text)
                    if response['payload']['message'] in xfer_response:
                        transfer = True
                        
                        mongoDB = app.mongo_client['jamesbon']
                        leads_col = mongoDB['leads']
                        search_query = {
                            "call_logs.call_id":call_id
                        }
                        lead = leads_col.find_one(search_query)
                        campaigns_col = mongoDB['campaigns']
                        campaign = campaigns_col.find_one({'_id':lead['campaign_id']})

                        xfer_number = campaign['did']
                        print(xfer_number)
                        xfer_caller_id = request.form.get("From")
                        if request.form.get("Direction") == 'outbound-api':
                            xfer_caller_id = request.form.get("To")
                        voice_response.dial(number=xfer_number, caller_id=xfer_caller_id)
                        voice_response_xml += f'''
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
                        if response['type'] == 'end' and transfer == False:
                            logger.debug("HANGUP CALL")
                            voice_response.hangup()
                            hangup = True
                    except:
                        pass
        else:
            msg_text = 'None'
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            for row in cur.execute(f"SELECT repeat_times FROM calls WHERE call_id = '{call_id}'"):
                repeat_times = row[0]
                repeat_times += 1
                cur.execute(f"update calls set repeat_times = {repeat_times} where call_id = '{call_id}'")
                con.commit()
                if repeat_times > 2:
                    
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
                    logger.debug(msg_text)

                    voice_response_xml += f'''
                    <Play>https://obama-care.s3.amazonaws.com/{msg_text}.mp3</Play>
                    '''
                    voice_response.play(f"https://obama-care.s3.amazonaws.com/{msg_text}.mp3")
                    audio_files.append(f"https://obama-care.s3.amazonaws.com/{msg_text}.mp3")
                    #voice_response.say(msg_text)

        if transfer == False:
            voice_response.append(gather)
    except:
        try:
            logger.debug('FAILED 1')
            
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
        except:
            logger.debug('FAILED 2')
            pass
        voice_response.hangup()
        hangup = True
    voice_response_xml += '''
        </GetInput>
    </Response>
    '''
    if hangup == True:
        voice_response_xml = '''<Response>
'''
        for audio in audio_files:
            voice_response_xml += f'''
                <Play>{audio}</Play>
            '''
        voice_response_xml += '''
    <Hangup reason="rejected" />
</Response>
        '''
    
    if request.args.get('active') == '1' and transfer == False:
        logger.debug(str(voice_response_xml))
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
    call_id = request.form.get('CallSid')
    mongoDB = app.mongo_client['jamesbon']
    leads_col = mongoDB['leads']
    search_query = {
        "call_logs.call_id":call_id
    }
    lead = leads_col.find_one(search_query)
    return_post = {}
    for data in lead['lead_data']:
        field_name = data['field_name']
        field_name = field_name.replace(' ', '_')
        return_post[field_name] = data['field_value']
    return jsonify(return_post)

@app.route('/transfer', methods=['POST'])
def transfer():
    return jsonify({'Message':'Success'})


'''PLIVO STUFF'''
@app.route('/plivo/call_back', methods=['POST'])
def plivoCallback():
    print(request.form)
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
        print(step)
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
    print(str(voice_response_xml))
    return Response(str(voice_response_xml), mimetype="text/xml")


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5005)
