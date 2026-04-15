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
    # Agora buscamos o ID também para poder deletar depois
    c.execute("SELECT id, data, tipo, categoria, valor, descricao FROM transacoes WHERE usuario = ?", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição'])

def deletar_transacao(id_transacao):
    c.execute("DELETE FROM transacoes WHERE id = ?", (id_transacao,))
    conn.commit()

# --- SISTEMA DE SESSÃO ---
if 'logado' not in st.session_state:
    st.session_state['logado'] = False
if 'usuario_atual' not in st.session_state:
    st.session_state['usuario_atual'] = ""

# --- TELA DE LOGIN / CADASTRO ---
if not st.session_state['logado']:
    st.title("🔒 Bem-vindo ao Sistema Financeiro")
    aba_login, aba_cadastro = st.tabs(["Fazer Login", "Criar Conta"])
    
    with aba_login:
        st.subheader("Acesse sua conta")
        usuario_login = st.text_input("Usuário", key="login_user")
        senha_login = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar"):
            if verificar_login(usuario_login, senha_login):
                st.session_state['logado'] = True
                st.session_state['usuario_atual'] = usuario_login
                st.rerun()
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
    
    # --- MENU LATERAL (PERSONALIZAÇÃO DE CORES) ---
    with st.sidebar.expander("🎨 Personalizar Visual"):
        cor_fundo = st.color_picker("Cor de Fundo", "#0E1117")
        cor_texto = st.color_picker("Cor do Texto", "#FAFAFA")
        
        # Injeta o CSS para mudar as cores do site em tempo real
        st.markdown(f"""
            <style>
            .stApp {{ background-color: {cor_fundo}; }}
            .stApp, h1, h2, h3, p, label {{ color: {cor_texto} !important; }}
            </style>
        """, unsafe_allow_html=True)
        
    st.sidebar.markdown("---")
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    st.sidebar.subheader("➕ Adicionar Lançamento")
    
    # REMOVEMOS O FORMULÁRIO para a caixinha atualizar instantaneamente
    tipo_lancamento = st.sidebar.selectbox("Tipo", ["Despesa", "Entrada"])
    
    if tipo_lancamento == "Despesa":
        categoria = st.sidebar.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Outros"])
    else:
        categoria = st.sidebar.selectbox("Categoria", ["Salário", "Freelance", "Rendimento", "Outros"])
        
    # Data no formato Dia/Mês/Ano
    data_lancamento = st.sidebar.date_input("Data", datetime.today(), format="DD/MM/YYYY")
    valor_lancamento = st.sidebar.number_input("Valor (R$)", min_value=0.01, format="%.2f")
    descricao_lancamento = st.sidebar.text_input("Descrição (Ex: Uber, Salário)")
    
    if st.sidebar.button("Salvar Lançamento"):
        adicionar_transacao(usuario, str(data_lancamento), tipo_lancamento, categoria, valor_lancamento, descricao_lancamento)
        st.sidebar.success("Adicionado com sucesso!")
        st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Seu Dashboard Financeiro")
    st.markdown("---")
    
    df = buscar_transacoes(usuario)
    
    if df.empty:
        st.info("Você ainda não tem lançamentos. Use o menu lateral para adicionar!")
    else:
        # Formata a data no Pandas para ficar DD/MM/YYYY
        df['Data'] = pd.to_datetime(df['Data']).dt.strftime('%d/%m/%Y')
        
        entradas = df[df['Tipo'] == 'Entrada']['Valor'].sum()
        despesas = df[df['Tipo'] == 'Despesa']['Valor'].sum()
        saldo = entradas - despesas
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Entradas", f"R$ {entradas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        with col2:
            st.metric("Despesas", f"R$ {despesas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        with col3:
            st.metric("Saldo Atual", f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta=f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            
        st.markdown("---")
        
        # --- GRÁFICOS ---
        col_graf1, col_graf2 = st.columns(2)
        
        df_despesas = df[df['Tipo'] == 'Despesa']
        df_entradas = df[df['Tipo'] == 'Entrada']
        
        with col_graf1:
            st.subheader("📉 Distribuição de Despesas")
            if not df_despesas.empty:
                resumo_despesas = df_despesas.groupby('Categoria')['Valor'].sum().reset_index()
                fig_rosca_desp = px.pie(resumo_despesas, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                st.plotly_chart(fig_rosca_desp, use_container_width=True)
            else:
                st.write("Sem despesas registradas.")
                
        with col_graf2:
            st.subheader("📈 Distribuição de Entradas")
            if not df_entradas.empty:
                resumo_entradas = df_entradas.groupby('Categoria')['Valor'].sum().reset_index()
                fig_rosca_ent = px.pie(resumo_entradas, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                st.plotly_chart(fig_rosca_ent, use_container_width=True)
            else:
                st.write("Sem entradas registradas.")
                
        st.markdown("---")
        
        # --- TABELA E DELETAR ---
        col_tabela, col_deletar = st.columns([2, 1])
        
        with col_tabela:
            st.subheader("📋 Extrato Detalhado")
            # Exibe a tabela formatando o valor para R$
            st.dataframe(
                df.style.format({'Valor': 'R$ {:.2f}'}), 
                use_container_width=True, 
                hide_index=True
            )
            
        with col_deletar:
            st.subheader("⚙️ Gerenciar Lançamentos")
            st.write("Para editar, exclua o lançamento incorreto e crie um novo.")
            
            # Cria uma lista bonita para a pessoa escolher qual deletar
            opcoes_deletar = df.apply(lambda row: f"{row['ID']} | {row['Data']} - {row['Descrição']} (R$ {row['Valor']})", axis=1).tolist()
            
            lancamento_selecionado = st.selectbox("Selecione para excluir:", opcoes_deletar)
            
            if st.button("🗑️ Excluir Lançamento"):
                if lancamento_selecionado:
                    id_para_deletar = lancamento_selecionado.split(" | ")[0]
                    deletar_transacao(id_para_deletar)
                    st.success("Lançamento apagado!")
                    st.rerun()