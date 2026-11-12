FROM python:3.13.8-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY crawling/dacon/requirements*.txt crawling/dacon/build.sh ./crawling/dacon/
# Install OS libraries and Chromium into the final image, not an ephemeral
# native-runtime build environment. The web service needs none of these.
RUN bash crawling/dacon/build.sh
COPY crawling/dacon/ ./crawling/dacon/
COPY crawling/contestkorea/ ./crawling/contestkorea/
COPY crawling/activities/ ./crawling/activities/
COPY apps/api/app/config.py ./apps/api/app/config.py
COPY apps/api/app/repositories/postgres.py ./apps/api/app/repositories/postgres.py
COPY apps/api/app/providers/external/contestkorea.py ./apps/api/app/providers/external/contestkorea.py
COPY apps/api/app/services/activity_eligibility.py ./apps/api/app/services/activity_eligibility.py
CMD ["python", "-m", "crawling.activities.run", "--mode", "scheduled"]
