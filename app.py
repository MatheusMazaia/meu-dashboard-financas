import pandas as pd
import io
import streamlit as st
import plotly.express as px

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Meu Dashboard", layout="wide")

# 1. Dados extraídos das suas faturas de Março
dados_csv = """Data|Estabelecimento|Método|Valor
31 MAR|ARCA SOLUCOES TECNOLOGICAS S/A|Pix|203.28
31 MAR|Uber|Crédito|12.24
30 MAR|Meli+|Crédito|19.90
29 MAR|iFood|Crédito|37.96
29 MAR|S A Micro Market|Crédito|26.58
29 MAR|iFood|Crédito|32.92
28 MAR|iFood|Crédito|39.10
28 MAR|iFood|Crédito|30.54
28 MAR|iFood|Crédito|27.17
28 MAR|HBO Max|Crédito|31.43
27 MAR|iFood|Nupay|20.99
27 MAR|iFood|Crédito|32.89
26 MAR|iFood|Nupay|27.23
26 MAR|Paramount+|Crédito|34.90
25 MAR|iFood|Crédito|25.67
25 MAR|Steam Games (Parcela)|Crédito|51.68
25 MAR|Uber|Crédito|11.73
24 MAR|iFood|Nupay|38.39
24 MAR|Dolce Cafe Panificadora|Pix|20.70
24 MAR|Uber|Crédito|9.63
23 MAR|iFood|Crédito|39.10
23 MAR|Uber|Pix|14.36
23 MAR|Uber|Pix|10.86
21 MAR|Itamar Martiniano Raimundo|Pix|14.00
21 MAR|61 529 305 EMERSON PARRA DOS SANTOS|Pix/Débito|12.00
20 MAR|Clube iFood|Débito|12.90
20 MAR|CEZALI E CIA LTDA|Pix|19.00
20 MAR|Uber|Pix|15.54
20 MAR|BROWNIE DO DE LTDA|Pix|8.50
19 MAR|S.A MICRO MARKET MINI MERCADO LTDA|Pix|20.89
19 MAR|iFood|Nupay|20.99
19 MAR|OLIVEIRA E OLIVEIRA PASSAGENS|Pix/Débito|378.00
18 MAR|iFood|Nupay|37.61
17 MAR|iFood|Nupay|39.10
16 MAR|Farmácias Nissei|Débito|106.80
16 MAR|Uber|Pix|9.94
16 MAR|Uber|Pix|10.82
16 MAR|iFood|Nupay|20.99
16 MAR|PagBank|Pix|7.99
16 MAR|iFood|Nupay|25.84
16 MAR|PANIFICADORA DELICIA|Débito|10.43
15 MAR|iFood|Nupay|58.96
15 MAR|iFood|Nupay|46.26
14 MAR|iFood|Nupay|26.56
14 MAR|iFood|Nupay|33.77
14 MAR|iFood|Nupay|22.34
13 MAR|iFood|Nupay|33.89
13 MAR|YouTube Premium|Crédito|16.90
13 MAR|iFood|Nupay|5.98
13 MAR|Uber|Pix|14.07
12 MAR|iFood|Nupay|32.99
12 MAR|Uber|Pix|15.76
11 MAR|Uber|Crédito|16.50
10 MAR|iFood|Nupay|22.37
10 MAR|Nubank+|Crédito|39.00
10 MAR|Uber|Crédito|23.06
10 MAR|Apple|Crédito|5.90
09 MAR|iFood|Nupay|39.78
09 MAR|iFood|Crédito|23.98
09 MAR|BROWNIE DO DE LTDA|Débito|8.50
08 MAR|S A MICRO MARKET|Débito|14.57
08 MAR|Capra|Crédito|87.79
08 MAR|iFood|Nupay|40.89
08 MAR|Teodoro Britez Benitez Neto|Pix|33.72
08 MAR|iFood|Nupay|33.56
07 MAR|iFood|Crédito|49.89
07 MAR|José Paulo Turini Torresan Lima|Pix|17.00
07 MAR|Uber|Crédito|10.43
07 MAR|Rafael Mazaia Mosca Lobo|Pix|17.40
07 MAR|Vinícius Souto Prates|Pix|20.00
06 MAR|iFood|Nupay|44.49
06 MAR|CANTINHO DO CAFE|Débito|13.00
06 MAR|Uber|Crédito|9.69
05 MAR|iFood|Crédito|23.39
05 MAR|Uber|Crédito|10.37
04 MAR|iFood|Crédito|39.10
04 MAR|iFood|Crédito|23.98
03 MAR|iFood|Crédito|19.48
03 MAR|W e Bolos|Crédito|49.00
03 MAR|Camilo Supermercados|Pix|4.78
03 MAR|Spotify|Crédito|23.90
03 MAR|Steam Games (Parcela 2/3)|Crédito|21.60
02 MAR|iFood|Crédito|19.48
02 MAR|Uber|Crédito|14.77
01 MAR|iFood|Crédito|17.99
01 MAR|iFood|Crédito|39.89
Fatura|Steam Games (Parcela 3/3)|Crédito|39.30
Fatura|Steam Games (Parcela 4/4)|Crédito|77.36
Fatura|Amazonmktplc*Tntinfoco (Parcela 4/9)|Crédito|381.66"""

# 2. Processamento dos Dados
df = pd.read_csv(io.StringIO(dados_csv), sep='|')
df['Valor'] = df['Valor'].astype(float)

def categorizar(estabelecimento):
    e = estabelecimento.lower()
    if any(palavra in e for palavra in ['ifood', 'cafe', 'brownie', 'market', 'panificadora', 'bolos', 'supermercado']):
        return 'Alimentação / Delivery'
    elif any(palavra in e for palavra in ['uber', 'passagens']):
        return 'Transporte'
    elif any(palavra in e for palavra in ['steam', 'amazon', 'apple', 'tecnologica', 'capra']):
        return 'Tecnologia / Compras / Jogos'
    elif any(palavra in e for palavra in ['premium', 'max', 'paramount', 'spotify', 'meli+', 'nubank+']):
        return 'Assinaturas / Streaming'
    elif 'nissei' in e:
        return 'Saúde / Farmácia'
    else:
        return 'Transferências / Outros / Serviços'

df['Categoria'] = df['Estabelecimento'].apply(categorizar)
resumo = df.groupby('Categoria')['Valor'].sum().reset_index()
resumo = resumo.sort_values(by='Valor', ascending=False)
total_gasto = df['Valor'].sum()

# --- BARRA LATERAL (MENU INTERATIVO) ---
st.sidebar.title("💰 Configurações")
st.sidebar.write("Insira seus ganhos para calcular o saldo:")
# Campo para você digitar o seu salário/rendimento
rendimento = st.sidebar.number_input("Rendimento Mensal (R$):", min_value=0.0, value=4000.0, step=100.0)

# Cálculo do Saldo
saldo = rendimento - total_gasto

# --- CONSTRUÇÃO DO DASHBOARD VISUAL ---
st.title("📊 Dashboard de Finanças Pessoais")
st.markdown("---")

# Criando "Cards" no estilo da sua imagem
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Entradas", value=f"R$ {rendimento:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

with col2:
    st.metric(label="Despesas", value=f"R$ {total_gasto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

with col3:
    # O "delta" faz a setinha verde para cima se positivo, ou vermelha para baixo se negativo!
    st.metric(
        label="Saldo Atual", 
        value=f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        delta=f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )

st.markdown("---")

# Criando as colunas para os Gráficos
graf_col1, graf_col2 = st.columns(2)

with graf_col1:
    st.subheader("Top Despesas por Categoria")
    fig_rosca = px.pie(resumo, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
    st.plotly_chart(fig_rosca, use_container_width=True)

with graf_col2:
    st.subheader("Gastos Detalhados")
    fig_barras = px.bar(resumo, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
    st.plotly_chart(fig_barras, use_container_width=True)

# Tabela interativa no final
st.subheader("Extrato Detalhado")
st.dataframe(df, use_container_width=True)