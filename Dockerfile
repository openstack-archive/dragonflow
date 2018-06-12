FROM ubuntu:16.04

# Install dependencies and some useful tools.
ENV DRAGONFLOW_PACKAGES git \
                  python-pip python-psutil python-subprocess32 python-dev libpython-dev

# Ignore questions when installing with apt-get:
ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install -y $DRAGONFLOW_PACKAGES

RUN mkdir -p /opt/dragonflow

# Get dragonflow to our docker
COPY . /opt/dragonflow/

# Get dragonflow to our docker
WORKDIR /opt/dragonflow
RUN pip install -e .

# Create config file
RUN mkdir -p /etc/dragonflow

ENTRYPOINT ["./tools/run_dragonflow.sh"]

