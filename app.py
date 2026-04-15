import streamlit as st
import pandas as pd
import plotly.express as px
import psycopg2
from psycopg2 import IntegrityError
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Meu Dashboard", layout="wide")

# --- CONEXÃO COM BANCO DE DADOS (PostgreSQL / Neon) ---
# O Streamlit esconde a conexão no cache para o site ficar muito rápido
@st.cache_resource
def init_connection():
    # Ele puxa a senha mágica lá daquele cofre que criamos!
    return psycopg2.connect(st.secrets["DATABASE_URL"])

conn = init_connection()
conn.autocommit = True # Salva tudo instantaneamente
c = conn.cursor()

# Cria as tabelas no Neon (se já não existirem)
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')

# --- FUNÇÕES DE SEGURANÇA E BANCO ---
def gerar_hash(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def adicionar_usuario(usuario, senha):
    c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))

def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao):
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao) VALUES (%s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, descricao))

def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao FROM transacoes WHERE usuario = %s", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição'])

def deletar_transacao(id_transacao):
    c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))

def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao):
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s WHERE id=%s", 
              (data, tipo, categoria, valor, descricao, id_transacao))

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
            user_limpo = usuario_login.strip().lower()
            if verificar_login(user_limpo, senha_login):
                st.session_state['logado'] = True
                st.session_state['usuario_atual'] = user_limpo
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos!")
                
    with aba_cadastro:
        st.subheader("Crie sua conta gratuitamente")
        novo_usuario = st.text_input("Novo Usuário")
        nova_senha = st.text_input("Nova Senha", type="password")
        if st.button("Cadastrar"):
            novo_user_limpo = novo_usuario.strip().lower()
            if novo_user_limpo == "" or nova_senha == "":
                st.warning("Por favor, preencha o usuário e a senha.")
            else:
                try:
                    adicionar_usuario(novo_user_limpo, nova_senha)
                    st.session_state['logado'] = True
                    st.session_state['usuario_atual'] = novo_user_limpo
                    st.success("Conta criada com sucesso! Carregando dashboard...")
                    st.rerun()
                # Tratamento de erro específico para usuários duplicados no Postgres
                except IntegrityError: 
                    st.error("Esse nome de usuário já existe. Escolha outro.")

# --- TELA PRINCIPAL (DASHBOARD) ---
else:
    usuario = st.session_state['usuario_atual']
    
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    st.sidebar.subheader("➕ Adicionar Lançamento")
    
    tipo_lancamento = st.sidebar.selectbox("Tipo", ["Despesa", "Entrada"])
    
    if tipo_lancamento == "Despesa":
        categoria = st.sidebar.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Outros"])
    else:
        categoria = st.sidebar.selectbox("Categoria", ["Salário", "Freelance", "Rendimento", "Outros"])
        
    data_lancamento = st.sidebar.date_input("Data", datetime.today(), format="DD/MM/YYYY")
    valor_lancamento = st.sidebar.number_input("Valor (R$)", min_value=0.01, format="%.2f")
    descricao_lancamento = st.sidebar.text_input("Descrição (Ex: Uber, Salário)")
    
    if st.sidebar.button("Salvar Lançamento"):
        adicionar_transacao(usuario, str(data_lancamento), tipo_lancamento, categoria, valor_lancamento, descricao_lancamento)
        st.sidebar.success("Adicionado com sucesso!")
        st.rerun()

    st.title("📊 Seu Dashboard Financeiro")
    st.markdown("---")
    
    df = buscar_transacoes(usuario)
    
    if df.empty:
        st.info("Você ainda não tem lançamentos. Use o menu lateral para adicionar!")
    else:
        df['Valor'] = df['Valor'].astype(float)
        
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
        
        df_despesas = df[df['Tipo'] == 'Despesa']
        df_entradas = df[df['Tipo'] == 'Entrada']
        
        st.subheader("📉 Visão de Despesas")
        col_graf_d1, col_graf_d2 = st.columns(2)
        with col_graf_d1:
            if not df_despesas.empty:
                resumo_desp = df_despesas.groupby('Categoria')['Valor'].sum().reset_index()
                fig_rosca_desp = px.pie(resumo_desp, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                st.plotly_chart(fig_rosca_desp, use_container_width=True)
            else:
                st.write("Sem despesas registradas.")
        with col_graf_d2:
            if not df_despesas.empty:
                fig_barras_desp = px.bar(resumo_desp, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
                st.plotly_chart(fig_barras_desp, use_container_width=True)

        st.subheader("📈 Visão de Entradas")
        col_graf_e1, col_graf_e2 = st.columns(2)
        with col_graf_e1:
            if not df_entradas.empty:
                resumo_ent = df_entradas.groupby('Categoria')['Valor'].sum().reset_index()
                fig_rosca_ent = px.pie(resumo_ent, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                st.plotly_chart(fig_rosca_ent, use_container_width=True)
            else:
                st.write("Sem entradas registradas.")
        with col_graf_e2:
            if not df_entradas.empty:
                fig_barras_ent = px.bar(resumo_ent, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
                st.plotly_chart(fig_barras_ent, use_container_width=True)
                
        st.markdown("---")
        
st.subheader("📋 Extrato Detalhado (Gerenciar Lançamentos)")
        st.info("💡 **Dica:** Para alterar algo, dê **dois cliques** em cima do valor. Para excluir, selecione o quadradinho no início da linha e aperte o botão 'Lixeira' (ou a tecla Delete). Depois, clique no botão vermelho para salvar!")
        
        df_editavel = df.copy()
        # Tratamento seguro da data para exibição no calendário
        df_editavel['Data'] = pd.to_datetime(df_editavel['Data'], format='mixed', dayfirst=True).dt.date
        
        mudancas = st.data_editor(
            df_editavel,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            key="editor_tabela",
            column_config={
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Entrada"]),
                "Categoria": st.column_config.SelectboxColumn("Categoria", options=["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Freelance", "Rendimento", "Outros"]),
                "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0)
            }
        )
        
        # --- O ESCUDO MÁGICO ---
        # Só tenta ler a tabela se ela já existir na memória do site
        if "editor_tabela" in st.session_state:
            if st.session_state["editor_tabela"]["edited_rows"] or st.session_state["editor_tabela"]["deleted_rows"]:
                if st.button("💾 Confirmar Alterações da Tabela", type="primary"):
                    
                    # 1. Deletando com conversão
                    for row_idx in st.session_state["editor_tabela"]["deleted_rows"]:
                        id_deletar = int(df.iloc[row_idx]["ID"])
                        deletar_transacao(id_deletar)
                    
                    # 2. Atualizando com conversão
                    for row_idx, alteracoes in st.session_state["editor_tabela"]["edited_rows"].items():
                        id_editar = int(df.iloc[int(row_idx)]["ID"])
                        linha_original = df.iloc[int(row_idx)].to_dict()
                        
                        for col, novo_valor in alteracoes.items():
                            linha_original[col] = novo_valor
                            
                        # Formatando o valor para float
                        valor_corrigido = float(linha_original["Valor"])
                            
                        atualizar_transacao(
                            id_editar, 
                            str(linha_original["Data"]), 
                            linha_original["Tipo"], 
                            linha_original["Categoria"], 
                            valor_corrigido, 
                            linha_original["Descrição"]
                        )
                        
                    st.success("Tabela atualizada com sucesso no Banco de Dados!")
                    st.rerun()