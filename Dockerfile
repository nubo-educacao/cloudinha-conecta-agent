FROM python:3.12-slim

WORKDIR /app

# Instalar dependências do sistema necessárias para algumas libs Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivos de configuração e instalar dependências
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copiar o restante do código
COPY . .

# Cloud Run utiliza por padrão a porta 8080
ENV PORT=8080
EXPOSE 8080

# Comando simplificado para garantir que o uvicorn inicie corretamente
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
