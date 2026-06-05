#!/bin/bash
PARENT_PATH=$(dirname "$(realpath "$0")")
export OLLAMA_MODELS="$PARENT_PATH/models"
echo "Starte portables Ollama von: $PARENT_PATH"
"$PARENT_PATH/ollama" serve
