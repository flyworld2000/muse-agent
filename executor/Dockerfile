FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY requirements.txt /tmp/executor-requirements.txt

RUN pip install --no-cache-dir -r /tmp/executor-requirements.txt \
    && useradd --system --uid 10002 --create-home executor \
    && mkdir -p /workspace /input /seed /output /executor/keys /tmp/muse-work /tmp/pytest-base \
    && chown -R executor:executor /workspace /tmp/muse-work /tmp/pytest-base

COPY --chown=executor:executor run.py policy.py proposal.py candidate.py approval.py /executor/
COPY --chown=executor:executor keys/ed25519-public.pem /executor/keys/ed25519-public.pem

USER 10002:10002

ENTRYPOINT ["python", "/executor/run.py"]
CMD ["test"]
