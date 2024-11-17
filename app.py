from flask import Flask, request, abort
from werkzeug.exceptions import HTTPException
import json
from multiprocessing import Process, Queue
import logging
from logging import handlers as logginghandlers
import os
import requests
import yaml
from enum import Enum
import time
from pydub import AudioSegment
from pydub.playback import play
import re
import boto3


app = Flask(__name__)


@app.route("/api/synthesize", methods=['POST'])
def post_api_synthesize():
    """API endpoint accepts a request for TTS speech synthesis.  The function only enters the data into the synthesis queue if the payload meets minimum specifications.

    Returns:
        HTTP: Returns an HTTP response to the requestor (see Swagger)
    """

    if "name" not in request.json:
        abort(400, "Missing 'name' field in request")

    if not isinstance(request.json['name'], str):
        abort(400, "Field 'name' must be a string")

    request.json['name'] = str(request.json['name']).strip()

    if len(request.json['name']) < 4:
        abort(400, "Field 'name' must be at least 3 characters in length")

    if len(request.json['name']) > 240:
        request.json['name'] = str(request.json['name'])[:240]

    if "sentences" not in request.json:
        abort(400, "Missing 'sentences' field in request")

    if not isinstance(request.json['sentences'], list):
        abort(400, "Field 'sentences' must be an array")

    if len(request.json['sentences']) < 1:
        abort(400, "There must be at least 1 sentence")

    for sentence in request.json['sentences']:
        if not isinstance(sentence, str):
            abort(400, "Not all sentences are of type string")

    qSynthesizer.put(request.json)  
    return "", 202


@app.route("/api/playback", methods=['POST'])
def post_api_playback():
    """API endpoint accepts a request for audio playback of a given filename.  The function only enters the data into the playback queue if the payload meets minimum specifications.

    Returns:
        HTTP: Returns an HTTP response to the requestor (see Swagger)
    """

    if "filename" not in request.json:
        abort(400, "Missing 'filename' field in request")

    if not isinstance(request.json['filename'], str):
        abort(400, "Field 'filename' must be a string")

    if not os.path.isfile(os.path.join(settings['audio_path'], request.json['filename'])):
        abort(404)

    qPlayback.put(request.json)  
    return "", 202


@app.errorhandler(404)
def not_found(error):
    """Handles all file not found responses

    Args:
        error (file not found): The error event (unused)

    Returns:
        HTTP: Returns an empty body with a status code of 404
    """
    return "", 404


@app.errorhandler(400)
def not_found(e):
    """Handles all bad request responses

    Args:
        e (exception): The error event

    Returns:
        HTTP: Returns body with a status code of 400
    """
    response = e.get_response()
    response.data = json.dumps({
        "message": e.description
    })
    response.content_type = "application/json"
    return response, 400


@app.errorhandler(HTTPException)
def all_exception_handler(e):
    """Handles all unknown errors

    Args:
        e (exception): The error event

    Returns:
        HTTP: Returns body with a status code of 500
    """
    response = e.get_response()
    response.data = json.dumps({
        "message": e.description
    })
    response.content_type = "application/json"
    return response, e.code


def worker_playback(queue:Queue, settings:dict) -> None:
    """Performs playback worker actions from queued requests

    Args:
        queue (Queue): Queue containing playback requests
        settings (dict): Global settings data

    """
    logger = logging.getLogger("worker_playback")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    logHandler = logginghandlers.RotatingFileHandler(os.path.join(os.path.realpath(os.path.dirname(__file__)), 'worker_playback.log'), maxBytes=10485760, backupCount=1)
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel(getLogLevel(settings))

    logger.debug("Playback worker started")

    class playerStates(Enum):
        IDLE = 0
        PLAYING = 2

    currentState = playerStates.IDLE

    while True:

        try:
            while queue.empty() == False:
                request = queue.get()

                logger.debug("Requested audio file be played: " + request['filename'] + "\tPath: " + os.path.join(settings['audio_path'], request['filename']) + "\tFormat: " +str(os.path.splitext(request['filename'])[1]).replace(".", ""))
                sound = AudioSegment.from_file(os.path.join(settings['audio_path'], request['filename']), format=str(os.path.splitext(request['filename'])[1]).replace(".", ""))

                if "playback_db" in settings:
                    gain_adjustment = settings['playback_db'] - sound.dBFS
                    sound = sound.apply_gain(gain_adjustment)
                    logger.debug("Applied gain of " + str(gain_adjustment))

                t = Process(target=play, args=(sound,))
                
                if currentState == playerStates.IDLE:
                    if "callbackUrl" in request:
                        callbackPayload = {"event":"PLAYBACK_START"}
                        sendCallback(request['callbackUrl'], callbackPayload)
                    currentState = playerStates.PLAYING
                    logger.debug("Playback started")
                
                t.start()
                time.sleep((len(sound) + settings['playback_wait_ms'])/1000) #Play is an async function that never completes -- pad settings['playback_wait_ms'] to the length of the audio file and then kill the process
                t.kill()

                if queue.empty() == True:
                    if currentState == playerStates.PLAYING:
                        if "callbackUrl" in request:
                            callbackPayload = {"event":"PLAYBACK_COMPLETE"}
                            sendCallback(request['callbackUrl'], callbackPayload)
                        currentState = playerStates.IDLE
                        logger.debug("Playback complete")

        except KeyboardInterrupt:
            logger.debug("Playback worker stopped")
            return False

        except Exception as ex:
            logger.exception(ex)
            pass

        finally:
            if queue.empty() == True:
                if currentState == playerStates.PLAYING:
                    if "callbackUrl" in request:
                        callbackPayload = {"event":"PLAYBACK_COMPLETE"}
                        sendCallback(request['callbackUrl'], callbackPayload)
                    currentState = playerStates.IDLE
                    logger.debug("Playback complete")


def sendCallback(url:str, payload:object):
    """Sends callback requests to the requested URL with the requested payload.  The response is ignored.

    Args:
        url (str): URL to send the payload
        payload (object): Payload to be sent
    """
    requests.post(url, json = payload)


def worker_synthesizer(queue:Queue, settings:dict) -> None:
    """Performs TTS synthesizer worker actions from queued requests

    Args:
        queue (Queue): Queue containing synthesizer requests
        settings (dict): Global settings data

    """
    logger = logging.getLogger("worker_synthesizer")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    logHandler = logginghandlers.RotatingFileHandler(os.path.join(os.path.realpath(os.path.dirname(__file__)), 'worker_synthesizer.log'), maxBytes=10485760, backupCount=1)
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel(getLogLevel(settings))

    logger.debug("Synthesizer worker started")

    pollyClient = boto3.Session(region_name=settings['aws']['region']).client('polly')

    while True:
        try:
            while queue.empty() == False:
                request = queue.get()

                filename = re.sub('[^0-9a-zA-Z]+', '_', request["name"].lower()).replace("__", "_") + ".mp3"
                filename = filename.replace("_.", ".")

                if "overwrite" not in request:
                    request['overwrite'] = False

                if "voice" not in request:
                    request["voice"] = settings['aws']['voice']

                if "engine" not in request:
                    request["engine"] = settings['aws']['engine']

                if "language" not in request:
                    request["language"] = settings['aws']['language']

                if not os.path.isfile(os.path.join(settings['audio_path'], filename)) or request['overwrite'] == True:

                    text = "<speak>"

                    for sentence in request["sentences"]:
                        text = text + "<s>" + sentence + "</s>"

                    text = text + "</speak>"

                    pollyResponse = pollyClient.synthesize_speech(
                        Engine = request["engine"],
                        LanguageCode = request["language"],
                        OutputFormat = "mp3",
                        Text = text,
                        TextType = 'ssml',
                        VoiceId = request["voice"]
                    )

                    file = open(os.path.join(settings['audio_path'], filename), 'wb')
                    file.write(pollyResponse['AudioStream'].read())
                    file.close()

                    logger.debug("Created or overwrote existing file " + os.path.join(settings['audio_path'], filename))

                if "callbackUrl" in request:
                    callbackPayload = {"event":"SYNTHESIS_COMPLETE"}
                    callbackPayload['filename'] = filename
                    sendCallback(request['callbackUrl'], callbackPayload)
                    logger.debug(callbackPayload)


        except KeyboardInterrupt:
            logger.debug("Synthesizer worker stopped")
            return False
        
        except Exception as ex:
            logger.exception(ex)
            pass


def getLogLevel(settings:dict) -> logging:
    """Retrieves the log level that should be observed based on the settings provided.

    Args:
        settings (dict): Observed settings

    Returns:
        logging: The log level that is in the observed settings
    """

    if str(settings['log_level']).lower() == "notset":
        return logging.NOTSET

    if str(settings['log_level']).lower() == "debug":
        return logging.DEBUG

    if str(settings['log_level']).lower() == "info":
        return logging.INFO

    if str(settings['log_level']).lower() == "warning":
        return logging.WARNING

    if str(settings['log_level']).lower() == "error":
        return logging.ERROR
    
    if str(settings['log_level']).lower() == "critical":
        return logging.CRITICAL


if __name__ == "__main__":
    global logger
    global qSynthesizer
    global qPlayback
    global settings
    settings = {}

    if os.path.isfile(os.path.join(os.path.realpath(os.path.dirname(__file__)), "settings.yaml")):
        with open(os.path.join(os.path.realpath(os.path.dirname(__file__)), "settings.yaml"), 'r') as f:
            settings = yaml.load(f, Loader=yaml.SafeLoader)

    if "http_port" not in settings:
        settings['http_port'] = 8080

    if "log_level" not in settings:
        settings['log_level'] = "INFO"

    if "playback_wait_ms" not in settings or isinstance(settings['playback_wait_ms'], int) == False:
        settings['playback_wait_ms'] = 350

    if "audio_path" not in settings:
        settings['audio_path'] = "/etc/P5Software/audio"

    if "aws" not in settings:
        settings['aws'] = {}

    if "region" not in settings['aws']:
        settings['aws']['region'] = "us-east-1"

    if "voice" not in settings['aws']:
        settings['aws']['voice'] = "Matthew"

    if "engine" not in settings['aws']:
        settings['aws']['engine'] = "neural"

    if "language" not in settings['aws']:
        settings['aws']['language'] = "en-US"

    if getLogLevel(settings) == logging.DEBUG:
        print("Observed Settings:")
        for entry in settings:
            print("\t", entry, ":", settings[entry])

    logger = logging.getLogger((__file__))
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    logHandler = logginghandlers.RotatingFileHandler(os.path.join(os.path.realpath(os.path.dirname(__file__)), __file__.replace(".py","") + '.log'), maxBytes=10485760, backupCount=1)
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel(getLogLevel(settings))

    logger.log(getLogLevel(settings), "Logging level set to " + str(getLogLevel(settings)))

    qSynthesizer = Queue()
    workerProcessSynthesizer = Process(target=worker_synthesizer, args=(qSynthesizer,settings,))
    logger.debug("Starting workerProcessSynthesizer")
    workerProcessSynthesizer.start()

    qPlayback = Queue()
    workerProcessPlayback = Process(target=worker_playback, args=(qPlayback,settings,))
    logger.debug("Starting workerProcessPlayback")
    workerProcessPlayback.start()

    logger.debug("Starting http on port " + str(settings['http_port']))
    from waitress import serve
    serve(app, host="0.0.0.0", port=settings['http_port'])