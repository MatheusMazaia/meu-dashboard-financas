import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Meu Dashboard", layout="wide")

# --- CONEXÃO COM BANCO DE DADOS (SQLite) ---
conn = sqlite3.connect('financas.db', check_same_thread=False)
c = conn.cursor()

# Criar tabelas se não existirem
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario TEXT PRIMARY KEY, senha TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, data TEXT, tipo TEXT, categoria TEXT, valor REAL, descricao TEXT)''')
conn.commit()

# --- FUNÇÕES DE SEGURANÇA E BANCO ---
def gerar_hash(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def adicionar_usuario(usuario, senha):
    c.execute("INSERT INTO usuarios (usuario, senha) VALUES (?, ?)", (usuario, gerar_hash(senha)))
    conn.commit()

def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = ? AND senha = ?", (usuario, gerar_hash(senha)))
    return c.fetchone()

def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao):
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao) VALUES (?, ?, ?, ?, ?, ?)", 
              (usuario, data, tipo, categoria, valor, descricao))
    conn.commit()

def buscar_transacoes(usuario):
    c.execute("SELECT data, tipo, categoria, valor, descricao FROM transacoes WHERE usuario = ?", (usuario,))
    dados = c.fetchall()
    # Converte para um DataFrame do Pandas para facilitar os gráficos
    return pd.DataFrame(dados, columns=['Data', 'Tipo', 'Categoria', 'Valor', 'Descrição'])

# --- SISTEMA DE SESSÃO ---
# Isso lembra se o usuário está logado ou não enquanto ele usa o app
if 'logado' not in st.session_state:
    st.session_state['logado'] = False
if 'usuario_atual' not in st.session_state:
    st.session_state['usuario_atual'] = ""

# --- TELA DE LOGIN / CADASTRO ---
if not st.session_state['logado']:
    st.title("🔒 Bem-vindo ao Sistema Financeiro")
    
    # Cria duas abas: uma para login e outra para criar conta
    aba_login, aba_cadastro = st.tabs(["Fazer Login", "Criar Conta"])
    
    with aba_login:
        st.subheader("Acesse sua conta")
        usuario_login = st.text_input("Usuário", key="login_user")
        senha_login = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar"):
            if verificar_login(usuario_login, senha_login):
                st.session_state['logado'] = True
                st.session_state['usuario_atual'] = usuario_login
                st.rerun() # Atualiza a tela
            else:
                st.error("Usuário ou senha incorretos!")
                
    with aba_cadastro:
        st.subheader("Crie sua conta gratuitamente")
        novo_usuario = st.text_input("Novo Usuário")
        nova_senha = st.text_input("Nova Senha", type="password")
        if st.button("Cadastrar"):
            try:
                adicionar_usuario(novo_usuario, nova_senha)
                st.success("Conta criada com sucesso! Vá na aba de Login para entrar.")
            except sqlite3.IntegrityError:
                st.error("Esse nome de usuário já existe. Escolha outro.")

# --- TELA PRINCIPAL (DASHBOARD) ---
else:
    usuario = st.session_state['usuario_atual']
    
    # --- BARRA LATERAL (MENU INTERATIVO) ---
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    st.sidebar.subheader("➕ Adicionar Lançamento")
    
    # Formulário para adicionar nova transação
    with st.sidebar.form("form_transacao", clear_on_submit=True):
        tipo_lancamento = st.selectbox("Tipo", ["Despesa", "Entrada"])
        data_lancamento = st.date_input("Data", datetime.today())
        
        if tipo_lancamento == "Despesa":
            categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Outros"])
        else:
            categoria = st.selectbox("Categoria", ["Salário", "Freelance", "Rendimento", "Outros"])
            
        valor_lancamento = st.number_input("Valor (R$)", min_value=0.01, format="%.2f")
        descricao_lancamento = st.text_input("Descrição (Ex: Uber, Mercado, etc)")
        
        btn_salvar = st.form_submit_button("Salvar Lançamento")
        
        if btn_salvar:
            adicionar_transacao(usuario, str(data_lancamento), tipo_lancamento, categoria, valor_lancamento, descricao_lancamento)
            st.sidebar.success("Adicionado com sucesso!")
            st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Seu Dashboard Financeiro")
    st.markdown("---")
    
    # Busca os dados desse usuário específico no banco de dados
    df = buscar_transacoes(usuario)
    
    if df.empty:
        st.info("Você ainda não tem lançamentos. Use o menu lateral para adicionar ganhos e gastos!")
    else:
        # Cálculos Matemáticos
        entradas = df[df['Tipo'] == 'Entrada']['Valor'].sum()
        despesas = df[df['Tipo'] == 'Despesa']['Valor'].sum()
        saldo = entradas - despesas
        
        # Cards Superiores
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Entradas", f"R$ {entradas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        with col2:
            st.metric("Despesas", f"R$ {despesas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        with col3:
            st.metric("Saldo Atual", f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta=f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            
        st.markdown("---")
        
        # Gráficos (Apenas se houver despesas)
        df_despesas = df[df['Tipo'] == 'Despesa']
        if not df_despesas.empty:
            resumo_cat = df_despesas.groupby('Categoria')['Valor'].sum().reset_index()
            
            graf_col1, graf_col2 = st.columns(2)
            with graf_col1:
                st.subheader("Distribuição de Despesas")
                fig_rosca = px.pie(resumo_cat, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                st.plotly_chart(fig_rosca, use_container_width=True)
                
            with graf_col2:
                st.subheader("Despesas por Categoria")
                fig_barras = px.bar(resumo_cat, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
                st.plotly_chart(fig_barras, use_container_width=True)
                
        # Tabela Detalhada no final
        st.subheader("Extrato Detalhado")
        st.dataframe(df, use_container_width=True)