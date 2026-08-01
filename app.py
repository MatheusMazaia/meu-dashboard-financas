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
@st.cache_resource(ttl=300)
def init_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

conn = init_connection()

try:
    conn.autocommit = True
    c = conn.cursor()
    c.execute("SELECT 1")
except (psycopg2.OperationalError, psycopg2.InterfaceError):
    st.cache_resource.clear()
    conn = init_connection()
    conn.autocommit = True
    c = conn.cursor()

# Criação de Tabelas (Agora com a tabela de METAS!)
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS metas (usuario VARCHAR(255), categoria VARCHAR(255), limite REAL, PRIMARY KEY (usuario, categoria))''')

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

# Funções das Metas
def salvar_meta(usuario, categoria, limite):
    c.execute("""
        INSERT INTO metas (usuario, categoria, limite) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (usuario, categoria) 
        DO UPDATE SET limite = EXCLUDED.limite
    """, (usuario, categoria, limite))

def buscar_metas(usuario):
    c.execute("SELECT categoria, limite FROM metas WHERE usuario = %s", (usuario,))
    return dict(c.fetchall())

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
                except IntegrityError: 
                    st.error("Esse nome de usuário já existe. Escolha outro.")

# --- TELA PRINCIPAL (DASHBOARD) ---
else:
    usuario = st.session_state['usuario_atual']
    
    # MENU LATERAL
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

    st.sidebar.markdown("---")
    
    # MENU LATERAL: METAS (NOVO)
    with st.sidebar.expander("🎯 Definir Meta de Gastos"):
        cat_meta = st.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Saúde", "Educação", "Outros"], key="cat_meta")
        valor_meta = st.number_input("Limite (R$)", min_value=1.0, format="%.2f", key="val_meta")
        if st.button("Salvar Meta"):
            salvar_meta(usuario, cat_meta, valor_meta)
            st.success(f"Meta de {cat_meta} salva!")
            st.rerun()

    # CORPO DO DASHBOARD
    st.title("📊 Seu Dashboard Financeiro")
    st.markdown("---")
    
    df = buscar_transacoes(usuario)
    
    if df.empty:
        st.info("Você ainda não tem lançamentos. Use o menu lateral para adicionar!")
    else:
        df['Valor'] = df['Valor'].astype(float)
        
        # Filtro de Meses
        df['Data_dt'] = pd.to_datetime(df['Data'])
        df['MesAno'] = df['Data_dt'].dt.strftime('%m/%Y')
        lista_meses = ["Todos os Meses"] + sorted(df['MesAno'].unique().tolist(), reverse=True)
        
        col_filtro, _ = st.columns([1, 3])
        with col_filtro:
            mes_selecionado = st.selectbox("📅 Filtrar por Mês", lista_meses)
            
        # NOVA FUNÇÃO: Gráfico de Evolução Anual
        st.subheader("📈 Evolução de Receitas e Despesas")
        df_linha = df.copy()
        df_linha['Mes_Data'] = df_linha['Data_dt'].dt.to_period('M').dt.to_timestamp()
        resumo_linha = df_linha.groupby(['Mes_Data', 'Tipo'])['Valor'].sum().reset_index()
        
        fig_linha = px.line(resumo_linha, x='Mes_Data', y='Valor', color='Tipo', markers=True,
                            template="plotly_dark", color_discrete_map={'Entrada': '#00CC96', 'Despesa': '#EF553B'})
        fig_linha.update_xaxes(title="", tickformat="%m/%Y")
        st.plotly_chart(fig_linha, use_container_width=True)
        
        # Aplica o filtro na tabela para o restante do app
        if mes_selecionado != "Todos os Meses":
            df_filtrado = df[df['MesAno'] == mes_selecionado]
        else:
            df_filtrado = df
            
        if df_filtrado.empty:
            st.warning("Nenhum lançamento encontrado para este período.")
        else:
            entradas = df_filtrado[df_filtrado['Tipo'] == 'Entrada']['Valor'].sum()
            despesas = df_filtrado[df_filtrado['Tipo'] == 'Despesa']['Valor'].sum()
            saldo = entradas - despesas
            
            # NOVA FUNÇÃO: Comparativo com o Mês Anterior
            delta_entrada = None
            delta_despesa = None
            delta_saldo = None
            
            if mes_selecionado != "Todos os Meses":
                mes_atual, ano_atual = map(int, mes_selecionado.split('/'))
                mes_ant = mes_atual - 1
                ano_ant = ano_atual
                if mes_ant == 0:
                    mes_ant = 12
                    ano_ant -= 1
                mes_ant_str = f"{mes_ant:02d}/{ano_ant}"
                
                df_ant = df[df['MesAno'] == mes_ant_str]
                entradas_ant = df_ant[df_ant['Tipo'] == 'Entrada']['Valor'].sum() if not df_ant.empty else 0
                despesas_ant = df_ant[df_ant['Tipo'] == 'Despesa']['Valor'].sum() if not df_ant.empty else 0
                saldo_ant = entradas_ant - despesas_ant
                
                delta_entrada = entradas - entradas_ant
                delta_despesa = despesas - despesas_ant
                delta_saldo = saldo - saldo_ant
            
            # Exibição dos Totais com as Setinhas
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Entradas", f"R$ {entradas:,.2f}", delta=float(delta_entrada) if delta_entrada is not None else None)
            with col2:
                # delta_color="inverse" faz a seta vermelha se a despesa SUBIR (o que é ruim)
                st.metric("Despesas", f"R$ {despesas:,.2f}", delta=float(delta_despesa) if delta_despesa is not None else None, delta_color="inverse")
            with col3:
                st.metric("Saldo Atual", f"R$ {saldo:,.2f}", delta=float(delta_saldo) if delta_saldo is not None else None)
                
            st.markdown("---")
            
            # NOVA FUNÇÃO: Barra de Metas / Orçamento
            st.subheader("🎯 Suas Metas Mensais")
            metas = buscar_metas(usuario)
            if metas and mes_selecionado != "Todos os Meses":
                for cat, limite in metas.items():
                    gasto_cat = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Categoria'] == cat)]['Valor'].sum()
                    pct = gasto_cat / limite if limite > 0 else 0
                    
                    st.write(f"**{cat}**: Gasto R$ {gasto_cat:.2f} de R$ {limite:.2f}")
                    # A barra não pode passar de 100% (1.0) no código, então limitamos com min()
                    st.progress(min(pct, 1.0))
                    
                    if pct >= 1.0:
                        st.error(f"⚠️ Você estourou o orçamento de {cat}!")
                    elif pct >= 0.8:
                        st.warning(f"Atenção! Você já usou {pct*100:.1f}% do limite de {cat}.")
            elif mes_selecionado == "Todos os Meses":
                st.info("Selecione um mês específico no filtro acima para acompanhar suas metas.")
            else:
                st.info("Você ainda não definiu metas. Use o menu lateral (🎯 Definir Meta) para criar.")
                
            st.markdown("---")
            
            # Gráficos Expansíveis
            df_despesas = df_filtrado[df_filtrado['Tipo'] == 'Despesa']
            df_entradas = df_filtrado[df_filtrado['Tipo'] == 'Entrada']
            
            with st.expander("📊 Visão Geral (Entradas vs Despesas)", expanded=True):
                if entradas > 0 or despesas > 0:
                    df_geral = pd.DataFrame({'Tipo': ['Entradas', 'Despesas'], 'Valor': [entradas, despesas]})
                    fig_geral = px.pie(df_geral, values='Valor', names='Tipo', hole=0.5, template="plotly_dark",
                                       color='Tipo', color_discrete_map={'Entradas': '#00CC96', 'Despesas': '#EF553B'})
                    st.plotly_chart(fig_geral, use_container_width=True)
                else:
                    st.write("Adicione movimentações para ver a Visão Geral.")

            with st.expander("📉 Visão de Despesas", expanded=False):
                col_graf_d1, col_graf_d2 = st.columns(2)
                with col_graf_d1:
                    if not df_despesas.empty:
                        resumo_desp = df_despesas.groupby('Categoria')['Valor'].sum().reset_index()
                        fig_rosca_desp = px.pie(resumo_desp, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                        st.plotly_chart(fig_rosca_desp, use_container_width=True)
                    else:
                        st.write("Sem despesas registradas neste período.")
                with col_graf_d2:
                    if not df_despesas.empty:
                        fig_barras_desp = px.bar(resumo_desp, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
                        st.plotly_chart(fig_barras_desp, use_container_width=True)

            with st.expander("📈 Visão de Entradas", expanded=False):
                col_graf_e1, col_graf_e2 = st.columns(2)
                with col_graf_e1:
                    if not df_entradas.empty:
                        resumo_ent = df_entradas.groupby('Categoria')['Valor'].sum().reset_index()
                        fig_rosca_ent = px.pie(resumo_ent, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                        st.plotly_chart(fig_rosca_ent, use_container_width=True)
                    else:
                        st.write("Sem entradas registradas neste período.")
                with col_graf_e2:
                    if not df_entradas.empty:
                        fig_barras_ent = px.bar(resumo_ent, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
                        st.plotly_chart(fig_barras_ent, use_container_width=True)
                        
            st.markdown("---")
            
            st.subheader("📋 Extrato Detalhado (Gerenciar Lançamentos)")
            st.info("💡 **Dica:** Para alterar algo, dê **dois cliques** em cima do valor. Para excluir, selecione o quadradinho no início da linha e aperte o botão 'Lixeira'. Depois, clique no botão vermelho para salvar!")
            
            df_editavel = df_filtrado.copy()
            df_editavel['Data'] = pd.to_datetime(df_editavel['Data']).dt.date
            df_editavel = df_editavel.drop(columns=['Data_dt', 'MesAno', 'Mes_Data'], errors='ignore')
            
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
            
            # NOVA FUNÇÃO: Botão de Exportar para Excel/CSV
            # O sep=';' separa as colunas pro Excel BR, e o utf-8-sig arruma os acentos!
            csv_dados = df_editavel.to_csv(index=False, sep=';').encode('utf-8-sig')
            nome_arquivo = f"extrato_{mes_selecionado.replace('/', '_')}.csv" if mes_selecionado != "Todos os Meses" else "extrato_completo.csv"
            
            st.download_button(
                label="📥 Baixar Planilha (Excel / CSV)",
                data=csv_dados,
                file_name=nome_arquivo,
                mime="text/csv",
            )
            
            if "editor_tabela" in st.session_state:
                if st.session_state["editor_tabela"]["edited_rows"] or st.session_state["editor_tabela"]["deleted_rows"]:
                    if st.button("💾 Confirmar Alterações da Tabela", type="primary"):
                        for row_idx in st.session_state["editor_tabela"]["deleted_rows"]:
                            id_deletar = int(df_editavel.iloc[row_idx]["ID"])
                            deletar_transacao(id_deletar)
                        
                        for row_idx, alteracoes in st.session_state["editor_tabela"]["edited_rows"].items():
                            id_editar = int(df_editavel.iloc[int(row_idx)]["ID"])
                            linha_original = df_editavel.iloc[int(row_idx)].to_dict()
                            for col, novo_valor in alteracoes.items():
                                linha_original[col] = novo_valor
                            valor_corrigido = float(linha_original["Valor"])
                            atualizar_transacao(id_editar, str(linha_original["Data"]), linha_original["Tipo"], linha_original["Categoria"], valor_corrigido, linha_original["Descrição"])
                            
                        st.success("Tabela atualizada com sucesso no Banco de Dados!")
                        st.rerun()
