FROM python:3.13-slim
WORKDIR /app
COPY Lampiadim_MVP/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home lampiadim
COPY --chown=lampiadim:lampiadim Lampiadim_MVP/ /app/Lampiadim_MVP/
COPY --chown=lampiadim:lampiadim dados/tratados/lampiadim/ /app/dados/tratados/lampiadim/
COPY --chown=lampiadim:lampiadim .streamlit/ /app/.streamlit/
USER lampiadim
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"
CMD ["python", "-m", "streamlit", "run", "Lampiadim_MVP/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
