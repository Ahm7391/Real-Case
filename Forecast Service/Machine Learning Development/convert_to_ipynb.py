import json
import os

def convert(filename, out_filename):
    with open(filename, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
        
    markers = [
        "MODEL ARCHITECTURE",
        "XGBoost MODEL",
        "EXTRACTION AND LOADING FUNCTIONS",
        "ALGORITHMS AND HELPER FUNCTIONS",
        "OPTUNA HYPERPARAMETER ALGORITHM",
        "PREDICTION ALGORITHM",
        "def inference_pipeline"
    ]
    
    lines = content.split('\n')
    
    cells = []
    current_cell = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        is_marker = any(marker in line for marker in markers)
        
        if is_marker:
            preceding_hashes = []
            while current_cell and current_cell[-1].strip().startswith('#') and all(c in '# -=' for c in current_cell[-1].strip()):
                preceding_hashes.insert(0, current_cell.pop())
            
            if current_cell:
                source_code = "\n".join(current_cell).strip()
                if source_code:
                    source_lines = [l + "\n" for l in source_code.split('\n')]
                    cells.append({
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": source_lines
                    })
                
            current_cell = preceding_hashes
            current_cell.append(line)
        else:
            current_cell.append(line)
            
        i += 1
        
    if current_cell:
        source_code = "\n".join(current_cell).strip()
        if source_code:
            source_lines = [l + "\n" for l in source_code.split('\n')]
            cells.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": source_lines
            })
        
    notebook = {
        "cells": cells,
        "metadata": {
            "language_info": {
                "name": "python"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }
    
    with open(out_filename, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=1)

if __name__ == "__main__":
    convert("prediction_master.py", "prediction_master.ipynb")
    print("Notebook created successfully.")
