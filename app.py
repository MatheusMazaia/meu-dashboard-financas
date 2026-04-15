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
    c.execute("SELECT id, data, tipo, categoria, valor, descricao FROM transacoes WHERE usuario = ?", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição'])

def deletar_transacao(id_transacao):
    c.execute("DELETE FROM transacoes WHERE id = ?", (id_transacao,))
    conn.commit()

# Nova função para atualizar os dados editados na tabela
def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao):
    c.execute("UPDATE transacoes SET data=?, tipo=?, categoria=?, valor=?, descricao=? WHERE id=?", 
              (data, tipo, categoria, valor, descricao, id_transacao))
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
                # MUDANÇA 1: Auto-login instantâneo após cadastrar!
                st.session_state['logado'] = True
                st.session_state['usuario_atual'] = novo_usuario
                st.success("Conta criada com sucesso! Carregando dashboard...")
                st.rerun()
            except sqlite3.IntegrityError:
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

    # --- CORPO DO DASHBOARD ---
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
        
        # --- MUDANÇA 3: OS 4 GRÁFICOS ---
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
        
        # --- MUDANÇA 2: A NOVA TABELA MÁGICA ---
        st.subheader("📋 Extrato Detalhado (Gerenciar Lançamentos)")
        st.info("💡 **Dica:** Para alterar algo, dê **dois cliques** em cima do valor. Para excluir, selecione o quadradinho no início da linha e aperte o botão 'Lixeira' (ou a tecla Delete). Depois, clique no botão vermelho para salvar!")
        
        # Prepara a data para o calendário funcionar dentro da tabela
        df_editavel = df.copy()
        df_editavel['Data'] = pd.to_datetime(df_editavel['Data']).dt.date
        
        # O data_editor é a evolução do dataframe
        mudancas = st.data_editor(
            df_editavel,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic", # Isso ativa a opção de apagar linhas!
            key="editor_tabela",
            column_config={
                "ID": st.column_config.NumberColumn("ID", disabled=True), # Ninguém mexe no ID!
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Entrada"]),
                "Categoria": st.column_config.SelectboxColumn("Categoria", options=["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Freelance", "Rendimento", "Outros"]),
                "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0)
            }
        )
        
        # O botão "Salvar" só aparece magicamente se a pessoa mexer em alguma coisa na tabela
        if st.session_state["editor_tabela"]["edited_rows"] or st.session_state["editor_tabela"]["deleted_rows"]:
            if st.button("💾 Confirmar Alterações da Tabela", type="primary"):
                
                # 1. Varre e apaga as linhas que foram pra lixeira
                for row_idx in st.session_state["editor_tabela"]["deleted_rows"]:
                    id_deletar = df.iloc[row_idx]["ID"]
                    deletar_transacao(id_deletar)
                
                # 2. Varre e atualiza as células que foram editadas
                for row_idx, alteracoes in st.session_state["editor_tabela"]["edited_rows"].items():
                    id_editar = df.iloc[int(row_idx)]["ID"]
                    linha_original = df.iloc[int(row_idx)].to_dict()
                    
                    for col, novo_valor in alteracoes.items():
                        linha_original[col] = novo_valor
                        
                    atualizar_transacao(
                        id_editar, 
                        str(linha_original["Data"]), 
                        linha_original["Tipo"], 
                        linha_original["Categoria"], 
                        linha_original["Valor"], 
                        linha_original["Descrição"]
                    )
                    
                st.success("Tabela atualizada com sucesso no Banco de Dados!")
                st.rerun()