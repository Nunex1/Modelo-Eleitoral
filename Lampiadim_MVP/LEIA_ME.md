# Lampiadim | MVP local

## Arquivos necessários na mesma pasta

- `app.py`
- `requirements.txt`
- `resultado_presidencial_2026_brasil.csv` (já criado no seu notebook)
- `perfil_demografico_municipios_2026.csv` (criar pelo notebook; instrução abaixo)
- `base cidades completa.xlsx` (já baixado)

No Notebook `analise_eleitoral.ipynb`, execute uma nova célula:

```python
perfil_completo.to_csv(
    "perfil_demografico_municipios_2026.csv",
    index=False,
    encoding="utf-8-sig"
)
```

## Instalar e iniciar no terminal PowerShell do VS Code

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra o endereço mostrado pelo Streamlit (normalmente http://localhost:8501).

## Interpretação

O dashboard mostra votos por candidatura e composição do eleitorado de forma **independente**. Não é possível atribuir os votos de uma candidatura ao sexo ou à identidade de gênero dos votantes, pois o voto é secreto. O chat é baseado em consultas determinísticas à base, não um modelo de IA generativa. A análise por DDD exige validar todas as correspondências entre municípios antes de interpretar totais territoriais. A tabela de identidade de gênero agrupa, somente para a apresentação, `NÃO INFORMADO` e `Prefere não informar`.
