# http-public-address
An HTTP server to provide TTS and play other audio outputs on a Raspberry Pi

# What does it do?
This is an HTTP API endpoint that serves two primary functions: text-to-speech (TTS) via AWS Polly; Playing the resulting audio file out to the on-board audio hardware.  This is designed to work with a Rapsberry Pi.


# Prerequisites
Install prerequisites from apt: 
`sudo apt-get install python3`


## Clone the source code from GitHub

`sudo sh`

`git clone https://github.com/BrentIO/http-public-address.git /etc/P5Software/http-public-address`

## Setup Virtual Environment

Change to the new source code directory:

`cd /etc/P5Software/http-public-address`

Create the virtual environment:

`python3 -m venv ./.venv`

::: info
Ensure that the .venv folder is not added to source control.
:::

Use PIP to download and install the prerequisites:

`/etc/P5Software/http-public-address/.venv/bin/pip install --no-cache-dir -r /etc/P5Software/http-public-address/requirements.txt`


# API Documentation

A [sequence diagram](sequence_diagram.svg) (with [source](sequence_diagram.txt)) and [Swagger document](swagger.yaml) are included.

# :warning: Security

There is no security whatsoever with this service.  If someone knows the URL and payload to access the service, they can submit requests.

# :money_with_wings: AWS Polly Costs Real Money

This service uses [Amazon Polly](https://aws.amazon.com/polly/), which costs [real money](https://aws.amazon.com/polly/pricing/).  Use at your own risk.


# Application Settings

Application settings are stored in the settings.yaml file.  Available settings and their default values are below:

| Setting | Description | Default Value |
| ------- | ----------- | ------------- |
| `http_port` | Port that the HTTP server will listen on for requests | `8080` |
| `log_level` | Verbosity of the log level (see https://docs.python.org/3/library/logging.html#logging-levels) | `info` |
| `audio_path` | Fully-qualified path where the audio files will be written to and read from | `/etc/P5Software/http-public-address/audio` |
| `playback_db` | If defined, the playback audio will have gain applied to ensure the decibel level is approximately the `playback_db` level.  Only playback is affected and the original file is not modified. | (None) |
| `playback_wait_ms` | Number of milliseconds that should be added to the length of the audio file after playing before the playback process is killed.  This may need to be adjusted on slower CPU's. | `350` |
| `aws -> region` | AWS region for Amazon Polly | `us-east-1` |
| `aws -> voice` | Default voice that will be used if a voice is not specified in the HTTP request | `Matthew` |
| `aws -> engine` | Polly synthesis engine that will be used if not specified in the HTTP request  | `neural` |
| `aws -> language` | Spoken langage for the voice synthesis if not specified in the HTTP request | `en-US` |