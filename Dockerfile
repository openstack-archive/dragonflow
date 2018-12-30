FROM ubuntu:16.04

# Install dependencies and some useful tools.
ENV DRAGONFLOW_PACKAGES git \
                  python-pip python-psutil python-subprocess32 \
                  python-dev libpython-dev

# Ignore questions when installing with apt-get:
ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install -y $DRAGONFLOW_PACKAGES

# Create config folder
ENV DRAGONFLOW_ETCDIR /etc/dragonflow
RUN mkdir -p $DRAGONFLOW_ETCDIR /opt/dragonflow /var/run/dragonflow

# Copy Dragonflow sources to the container
COPY . /opt/dragonflow/

# Install Dragonflow on the container
WORKDIR /opt/dragonflow
RUN pip install -e .

ENTRYPOINT ["/opt/dragonflow/tools/run_dragonflow.sh"]

