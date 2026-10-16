FROM python@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
      communitywatch-web==0.1.0 \
    && rm -rf /wheels

USER 65532:65532
ENTRYPOINT ["communitywatch-history-demo"]
