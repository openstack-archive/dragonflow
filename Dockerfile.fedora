FROM fedora:latest

RUN dnf install -y git python3-pip python3-psutil python3-devel \
                  "@C Development Tools and Libraries"

RUN alternatives --install /usr/bin/python python /usr/bin/python3 1
RUN alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Create config folder
ENV DRAGONFLOW_ETCDIR /etc/dragonflow
RUN mkdir -p $DRAGONFLOW_ETCDIR /opt/dragonflow /var/run/dragonflow

# Copy Dragonflow sources to the container
COPY . /opt/dragonflow/

# Install Dragonflow on the container
WORKDIR /opt/dragonflow
RUN pip install -e .

ENTRYPOINT ["/opt/dragonflow/tools/run_dragonflow.sh"]

