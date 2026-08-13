import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2 import IntegrityError
import hashlib
from datetime import datetime, timedelta
import calendar

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mazaia Finance", layout="wide")

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

# --- CRIAÇÃO DE TABELAS ---
c.execute('''CREATE TABLE IF NOT EXISTS usuarios (usuario VARCHAR(255) PRIMARY KEY, senha VARCHAR(255))''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), categoria VARCHAR(255), valor REAL, descricao TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS metas (usuario VARCHAR(255), categoria VARCHAR(255), limite REAL, PRIMARY KEY (usuario, categoria))''')
c.execute('''CREATE TABLE IF NOT EXISTS investimentos (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), tipo VARCHAR(50), valor REAL, descricao TEXT)''')

# Novas Tabelas para o Vale Alimentação (VA)
c.execute('''CREATE TABLE IF NOT EXISTS va_config (usuario VARCHAR(255) PRIMARY KEY, saldo REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS va_transacoes (id SERIAL PRIMARY KEY, usuario VARCHAR(255), data VARCHAR(255), valor REAL, descricao TEXT)''')

# --- ATUALIZAÇÃO DO BANCO (MIGRAÇÕES AUTOMÁTICAS) ---
def check_and_add_column(table, column, col_type, default_val):
    c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' and column_name='{column}'")
    if not c.fetchone():
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default_val}'")

check_and_add_column('transacoes', 'conta', 'VARCHAR(255)', 'Geral')
check_and_add_column('transacoes', 'status', 'VARCHAR(50)', 'Pago')
check_and_add_column('transacoes', 'forma_pagamento', 'VARCHAR(50)', 'Débito')

# --- FUNÇÕES DE SEGURANÇA E BANCO ---
def gerar_hash(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def adicionar_usuario(usuario, senha):
    c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))

def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

# Funções Lançamentos Padrão
def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento))

def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento FROM transacoes WHERE usuario = %s", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta', 'Status', 'Forma de Pagamento'])

def deletar_transacao(id_transacao):
    c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))

def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s, conta=%s, status=%s, forma_pagamento=%s WHERE id=%s", 
              (data, tipo, categoria, valor, descricao, conta, status, forma_pagamento, id_transacao))

# Funções VA
def salvar_config_va(usuario, saldo):
    c.execute("INSERT INTO va_config (usuario, saldo) VALUES (%s, %s) ON CONFLICT (usuario) DO UPDATE SET saldo = EXCLUDED.saldo", (usuario, saldo))

def buscar_config_va(usuario):
    c.execute("SELECT saldo FROM va_config WHERE usuario = %s", (usuario,))
    res = c.fetchone()
    return res[0] if res else 0.0

def adicionar_transacao_va(usuario, data, valor, descricao):
    c.execute("INSERT INTO va_transacoes (usuario, data, valor, descricao) VALUES (%s, %s, %s, %s)", (usuario, data, valor, descricao))

def buscar_transacoes_va(usuario):
    c.execute("SELECT id, data, valor, descricao FROM va_transacoes WHERE usuario = %s", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Valor', 'Descrição'])

def deletar_transacao_va(id_transacao):
    c.execute("DELETE FROM va_transacoes WHERE id = %s", (id_transacao,))

def atualizar_transacao_va(id_transacao, data, valor, descricao):
    c.execute("UPDATE va_transacoes SET data=%s, valor=%s, descricao=%s WHERE id=%s", (data, valor, descricao, id_transacao))

# Outras Funções
def salvar_meta(usuario, categoria, limite):
    c.execute("INSERT INTO metas (usuario, categoria, limite) VALUES (%s, %s, %s) ON CONFLICT (usuario, categoria) DO UPDATE SET limite = EXCLUDED.limite", (usuario, categoria, limite))

def buscar_metas(usuario):
    c.execute("SELECT categoria, limite FROM metas WHERE usuario = %s", (usuario,))
    return dict(c.fetchall())

def adicionar_investimento(usuario, data, tipo, valor, descricao):
    c.execute("INSERT INTO investimentos (usuario, data, tipo, valor, descricao) VALUES (%s, %s, %s, %s, %s)", (usuario, data, tipo, valor, descricao))

def buscar_investimentos(usuario):
    c.execute("SELECT id, data, tipo, valor, descricao FROM investimentos WHERE usuario = %s", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Tipo', 'Valor', 'Descrição'])

def deletar_investimento(id_inv):
    c.execute("DELETE FROM investimentos WHERE id = %s", (id_inv,))

def add_months(sourcedate, months):
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day).date()

# --- SISTEMA DE SESSÃO ---
if 'logado' not in st.session_state:
    st.session_state['logado'] = False
if 'usuario_atual' not in st.session_state:
    st.session_state['usuario_atual'] = ""

# --- TELA DE LOGIN / CADASTRO ---
if not st.session_state['logado']:
    st.title("🔒 Bem-vindo ao Mazaia Finance")
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
    
    # --- MENU LATERAL ---
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    
    aba_lancamento, aba_va, aba_investimento = st.sidebar.tabs(["💸 Gastos", "🍔 VA", "📈 Investir"])
    
    with aba_lancamento:
        tipo_lancamento = st.selectbox("Tipo", ["Despesa", "Entrada"], key="tipo_lanc")
        if tipo_lancamento == "Despesa":
            categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros"], key="cat_lanc")
        else:
            categoria = st.selectbox("Categoria", ["Salário", "Freelance", "Rendimento", "Outros"], key="cat_lanc")
            
        conta_lancamento = st.selectbox("Conta / Instituição", ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra"], key="conta_lanc")
        forma_pagamento = st.selectbox("Forma de Pagamento", ["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"], key="forma_pag")
        status_lancamento = st.selectbox("Status", ["Pago", "Pendente"], key="status_lanc")
            
        data_lancamento = st.date_input("Data", datetime.today(), format="DD/MM/YYYY", key="data_lanc")
        valor_lancamento = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", key="valor_lanc")
        descricao_lancamento = st.text_input("Descrição (Ex: Uber, Salário)", key="desc_lanc")
        
        parcelas = 1
        if tipo_lancamento == "Despesa":
            eh_parcelado = st.checkbox("Compra Parcelada?", key="chk_parcela")
            if eh_parcelado:
                parcelas = st.number_input("Número de Parcelas", min_value=2, max_value=72, value=2, step=1, key="num_parcelas")
                st.info(f"Serão gerados {parcelas} lançamentos de R$ {(valor_lancamento/parcelas):.2f}")
        
        if st.button("Salvar Lançamento", type="primary", use_container_width=True):
            if parcelas == 1:
                adicionar_transacao(usuario, str(data_lancamento), tipo_lancamento, categoria, valor_lancamento, descricao_lancamento, conta_lancamento, status_lancamento, forma_pagamento)
            else:
                valor_parcela = valor_lancamento / parcelas
                for i in range(parcelas):
                    data_parcela = add_months(data_lancamento, i)
                    desc_parcela = f"{descricao_lancamento} ({i+1}/{parcelas})"
                    adicionar_transacao(usuario, str(data_parcela), tipo_lancamento, categoria, valor_parcela, desc_parcela, conta_lancamento, status_lancamento, forma_pagamento)
            st.success("Lançamento(s) salvo(s) com sucesso!")
            st.rerun()

    with aba_va:
        st.markdown("**1. Configurar Recarga do Mês**")
        saldo_atual_va = buscar_config_va(usuario)
        novo_saldo_va = st.number_input("Valor Recebido de VA (R$)", min_value=0.0, format="%.2f", value=float(saldo_atual_va), key="input_saldo_va")
        if st.button("Atualizar Recarga", use_container_width=True):
            salvar_config_va(usuario, novo_saldo_va)
            st.success("Recarga atualizada!")
            st.rerun()
            
        st.markdown("---")
        st.markdown("**2. Registrar Gasto do VA**")
        data_va = st.date_input("Data da Compra", datetime.today(), format="DD/MM/YYYY", key="data_va")
        valor_va = st.number_input("Valor da Compra (R$)", min_value=0.01, format="%.2f", key="valor_va")
        desc_va = st.text_input("Estabelecimento (Ex: Mercado, Padaria)", key="desc_va")
        
        if st.button("Salvar Gasto VA", type="primary", use_container_width=True):
            adicionar_transacao_va(usuario, str(data_va), valor_va, desc_va)
            st.success("Gasto registrado!")
            st.rerun()

    with aba_investimento:
        tipo_inv = st.selectbox("Tipo de Investimento", ["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "Fundos Imobiliários (FIIs)", "Criptomoedas", "Previdência", "Outros"])
        data_inv = st.date_input("Data da Aplicação", datetime.today(), format="DD/MM/YYYY", key="data_inv")
        valor_inv = st.number_input("Valor Investido (R$)", min_value=0.01, format="%.2f", key="valor_inv")
        desc_inv = st.text_input("Descrição (Ex: CDB Itaú, PETR4)", key="desc_inv")
        
        if st.button("Salvar Investimento", type="primary", use_container_width=True):
            adicionar_investimento(usuario, str(data_inv), tipo_inv, valor_inv, desc_inv)
            st.success("Investimento salvo!")
            st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Mazaia Finance")
    
    aba_visao_geral, aba_modulo_va, aba_carteira, aba_saude = st.tabs(["💰 Fluxo de Caixa", "🍔 Vale Alimentação", "💼 Investimentos", "🏆 Análise & Saúde"])
    
    # ----------------------------------------
    # ABA 1: FLUXO DE CAIXA E VENCIMENTOS
    # ----------------------------------------
    with aba_visao_geral:
        df = buscar_transacoes(usuario)
        
        if df.empty:
            st.info("Você ainda não tem lançamentos. Use o menu lateral para adicionar!")
        else:
            df['Valor'] = df['Valor'].astype(float)
            
            df['Data_dt'] = pd.to_datetime(df['Data'])
            df['MesAno'] = df['Data_dt'].dt.strftime('%m/%Y')
            lista_meses = ["Todos os Meses"] + sorted(df['MesAno'].unique().tolist(), reverse=True)
            
            col_filtro, _ = st.columns([1, 3])
            with col_filtro:
                mes_selecionado = st.selectbox("📅 Filtrar por Mês", lista_meses)
            
            # --- NOVO: Central de Vencimentos ---
            hoje = datetime.today().date()
            df_pendentes = df[df['Status'] == 'Pendente'].copy()
            if not df_pendentes.empty:
                df_pendentes['Data_Real'] = pd.to_datetime(df_pendentes['Data']).dt.date
                atrasadas = df_pendentes[df_pendentes['Data_Real'] < hoje]
                vencem_hoje = df_pendentes[df_pendentes['Data_Real'] == hoje]
                proximos_dias = df_pendentes[(df_pendentes['Data_Real'] > hoje) & (df_pendentes['Data_Real'] <= hoje + timedelta(days=5))]
                
                if not atrasadas.empty or not vencem_hoje.empty or not proximos_dias.empty:
                    st.subheader("📅 Central de Vencimentos (Avisos Importantes)")
                    col_v1, col_v2, col_v3 = st.columns(3)
                    with col_v1:
                        if not atrasadas.empty:
                            st.error(f"🔴 {len(atrasadas)} Conta(s) Atrasada(s)!\nTotal: R$ {atrasadas['Valor'].sum():.2f}")
                    with col_v2:
                        if not vencem_hoje.empty:
                            st.warning(f"🟡 {len(vencem_hoje)} Vencendo HOJE!\nTotal: R$ {vencem_hoje['Valor'].sum():.2f}")
                    with col_v3:
                        if not proximos_dias.empty:
                            st.info(f"🔵 {len(proximos_dias)} nos próximos 5 dias\nTotal: R$ {proximos_dias['Valor'].sum():.2f}")
                    st.markdown("---")

            if mes_selecionado != "Todos os Meses":
                df_filtrado = df[df['MesAno'] == mes_selecionado]
            else:
                df_filtrado = df
                
            if df_filtrado.empty:
                st.warning("Nenhum lançamento encontrado para este período.")
            else:
                entradas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Entrada') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                despesas_pagas = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pago')]['Valor'].sum()
                saldo_real = entradas_pagas - despesas_pagas
                contas_a_pagar = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Status'] == 'Pendente')]['Valor'].sum()
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Entradas (Recebidas)", f"R$ {entradas_pagas:,.2f}")
                with col2:
                    st.metric("Despesas (Pagas)", f"R$ {despesas_pagas:,.2f}")
                with col3:
                    st.metric("Saldo Atual", f"R$ {saldo_real:,.2f}")
                with col4:
                    st.metric("⚠️ A Pagar (Pendentes)", f"R$ {contas_a_pagar:,.2f}")
                    
                st.markdown("---")
                
                # Gráficos Expansíveis
                df_despesas = df_filtrado[df_filtrado['Tipo'] == 'Despesa']
                
                with st.expander("💳 Formas de Pagamento", expanded=False):
                    if not df_despesas.empty:
                        resumo_pag = df_despesas.groupby('Forma de Pagamento')['Valor'].sum().reset_index()
                        fig_pag = px.pie(resumo_pag, values='Valor', names='Forma de Pagamento', hole=0.4, template="plotly_dark")
                        st.plotly_chart(fig_pag, use_container_width=True)

                with st.expander("📉 Visão de Despesas por Categoria", expanded=False):
                    col_graf_d1, col_graf_d2 = st.columns(2)
                    with col_graf_d1:
                        if not df_despesas.empty:
                            resumo_desp = df_despesas.groupby('Categoria')['Valor'].sum().reset_index()
                            fig_rosca_desp = px.pie(resumo_desp, values='Valor', names='Categoria', hole=0.5, template="plotly_dark")
                            st.plotly_chart(fig_rosca_desp, use_container_width=True)
                    with col_graf_d2:
                        if not df_despesas.empty:
                            fig_barras_desp = px.bar(resumo_desp, x='Categoria', y='Valor', text_auto='.2f', template="plotly_dark")
                            st.plotly_chart(fig_barras_desp, use_container_width=True)
                            
                st.markdown("---")
                st.subheader("📋 Extrato Detalhado")
                
                df_editavel = df_filtrado.copy()
                df_editavel['Data'] = pd.to_datetime(df_editavel['Data']).dt.date
                df_editavel = df_editavel.drop(columns=['Data_dt', 'MesAno', 'Data_Real'], errors='ignore')
                
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
                        "Categoria": st.column_config.SelectboxColumn("Categoria", options=["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Freelance", "Rendimento", "Outros"]),
                        "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0),
                        "Conta": st.column_config.SelectboxColumn("Conta", options=["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra"]),
                        "Forma de Pagamento": st.column_config.SelectboxColumn("Forma de Pagamento", options=["Pix", "Débito", "Crédito", "Dinheiro", "Boleto"]),
                        "Status": st.column_config.SelectboxColumn("Status", options=["Pago", "Pendente"])
                    }
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
                                atualizar_transacao(id_editar, str(linha_original["Data"]), linha_original["Tipo"], linha_original["Categoria"], valor_corrigido, linha_original["Descrição"], linha_original["Conta"], linha_original["Status"], linha_original["Forma de Pagamento"])
                            st.success("Tabela atualizada com sucesso no Banco de Dados!")
                            st.rerun()

    # ----------------------------------------
    # ABA 2: MÓDULO EXCLUSIVO VA
    # ----------------------------------------
    with aba_modulo_va:
        st.subheader("🍔 Gestão do Vale Alimentação")
        
        saldo_configurado = buscar_config_va(usuario)
        df_va = buscar_transacoes_va(usuario)
        
        # Filtro mensal exclusivo pro VA
        if not df_va.empty:
            df_va['Data_dt'] = pd.to_datetime(df_va['Data'])
            df_va['MesAno'] = df_va['Data_dt'].dt.strftime('%m/%Y')
            lista_meses_va = ["Todos os Meses"] + sorted(df_va['MesAno'].unique().tolist(), reverse=True)
            mes_va_selecionado = st.selectbox("📅 Mês VA", lista_meses_va, key="filtro_va")
            
            if mes_va_selecionado != "Todos os Meses":
                df_va_filtrado = df_va[df_va['MesAno'] == mes_va_selecionado]
            else:
                df_va_filtrado = df_va
        else:
            df_va_filtrado = pd.DataFrame(columns=['ID', 'Data', 'Valor', 'Descrição'])
            
        total_gasto_va = df_va_filtrado['Valor'].sum() if not df_va_filtrado.empty else 0
        saldo_disponivel_va = saldo_configurado - total_gasto_va
        
        col_va1, col_va2, col_va3 = st.columns(3)
        with col_va1:
            st.metric("Recarga do Mês", f"R$ {saldo_configurado:.2f}")
        with col_va2:
            st.metric("Total Gasto", f"R$ {total_gasto_va:.2f}")
        with col_va3:
            st.metric("Disponível", f"R$ {saldo_disponivel_va:.2f}")
            
        st.markdown("---")
        
        # --- Gráfico de Barra Horizontal 100% (Porcentagem) ---
        if saldo_configurado > 0:
            pct_gasto = (total_gasto_va / saldo_configurado) * 100
            pct_restante = 100 - pct_gasto if pct_gasto <= 100 else 0
            
            # Ajuste caso estoure o limite
            if pct_gasto > 100:
                df_bar_va = pd.DataFrame({'Status': ['Estourado'], 'Porcentagem': [100], 'Texto': [f"{pct_gasto:.1f}%"]})
                cores_va = {'Estourado': '#EF553B'}
            else:
                df_bar_va = pd.DataFrame({
                    'Status': ['Gasto', 'Disponível'],
                    'Porcentagem': [pct_gasto, pct_restante],
                    'Texto': [f"{pct_gasto:.1f}%", f"{pct_restante:.1f}%"]
                })
                cores_va = {'Gasto': '#EF553B', 'Disponível': '#00CC96'}

            fig_bar_va = px.bar(df_bar_va, x='Porcentagem', y=['Vale Alimentação']*len(df_bar_va), color='Status', 
                                orientation='h', text='Texto', color_discrete_map=cores_va, template="plotly_dark",
                                title="Porcentagem de Consumo do VA")
            fig_bar_va.update_layout(xaxis=dict(range=[0, 100]))
            st.plotly_chart(fig_bar_va, use_container_width=True)
        else:
            st.info("Configure a recarga do mês no menu lateral para visualizar o gráfico de barra.")
            
        st.markdown("---")
        st.write("**Extrato do VA**")
        if not df_va_filtrado.empty:
            df_va_edit = df_va_filtrado.copy()
            df_va_edit['Data'] = pd.to_datetime(df_va_edit['Data']).dt.date
            df_va_edit = df_va_edit.drop(columns=['Data_dt', 'MesAno'], errors='ignore')
            
            editor_va = st.data_editor(
                df_va_edit, hide_index=True, use_container_width=True, key="editor_tabela_va",
                column_config={"ID": st.column_config.NumberColumn(disabled=True), "Data": st.column_config.DateColumn(format="DD/MM/YYYY"), "Valor": st.column_config.NumberColumn(format="R$ %.2f")}
            )
            
            if st.session_state.get("editor_tabela_va", {}).get("deleted_rows"):
                if st.button("🗑️ Confirmar Exclusão no VA", type="primary"):
                    for row_idx in st.session_state["editor_tabela_va"]["deleted_rows"]:
                        id_del = int(df_va_edit.iloc[row_idx]["ID"])
                        deletar_transacao_va(id_del)
                    st.success("Removido com sucesso!")
                    st.rerun()

    # ----------------------------------------
    # ABA 3: CARTEIRA DE INVESTIMENTOS
    # ----------------------------------------
    with aba_carteira:
        st.subheader("💼 Meu Patrimônio Acumulado")
        df_inv = buscar_investimentos(usuario)
        
        if df_inv.empty:
            st.info("Você ainda não tem investimentos cadastrados.")
        else:
            total_investido = df_inv['Valor'].sum()
            st.metric("Total Investido", f"R$ {total_investido:,.2f}")
            
            col_inv1, col_inv2 = st.columns([1, 1])
            with col_inv1:
                resumo_inv = df_inv.groupby('Tipo')['Valor'].sum().reset_index()
                fig_inv = px.pie(resumo_inv, values='Valor', names='Tipo', hole=0.4, template="plotly_dark")
                st.plotly_chart(fig_inv, use_container_width=True)
            with col_inv2:
                df_inv_editavel = df_inv.copy()
                df_inv_editavel['Data'] = pd.to_datetime(df_inv_editavel['Data']).dt.date
                st.data_editor(df_inv_editavel, hide_index=True, use_container_width=True, disabled=True)

    # ----------------------------------------
    # ABA 4: SAÚDE FINANCEIRA & GAMIFICAÇÃO
    # ----------------------------------------
    with aba_saude:
        st.subheader("🏆 Raio-X Financeiro do Mês")
        
        # Filtro de mês apenas para essa aba
        df_saude = buscar_transacoes(usuario)
        df_saude['Valor'] = df_saude['Valor'].astype(float)
        df_saude['Data_dt'] = pd.to_datetime(df_saude['Data'])
        df_saude['MesAno'] = df_saude['Data_dt'].dt.strftime('%m/%Y')
        
        meses_saude = sorted(df_saude['MesAno'].unique().tolist(), reverse=True)
        if meses_saude:
            mes_analise = st.selectbox("Escolha o mês para análise", meses_saude, key="mes_saude")
            df_mes = df_saude[df_saude['MesAno'] == mes_analise]
            
            # --- CÁLCULO DO SCORE (0 a 100) ---
            score = 50 # Base
            
            entradas_s = df_mes[df_mes['Tipo'] == 'Entrada']['Valor'].sum()
            despesas_s = df_mes[df_mes['Tipo'] == 'Despesa']['Valor'].sum()
            pendentes_s = df_mes[(df_mes['Tipo'] == 'Despesa') & (df_mes['Status'] == 'Pendente')]['Valor'].sum()
            
            if entradas_s > 0:
                # Regra 1: Gastou menos do que ganhou (+30) ou estourou (-30)
                if despesas_s <= entradas_s:
                    score += 30
                else:
                    score -= 30
                    
                # Regra 2: Poupou/Sobrou mais de 20% (+20)
                if (entradas_s - despesas_s) >= (entradas_s * 0.20):
                    score += 20
                    
                # Regra 3: Excesso de pendências
                if pendentes_s > (entradas_s * 0.30):
                    score -= 15
            else:
                score = 0
                
            # Limitar score entre 0 e 100
            score = max(0, min(100, score))
            
            col_s1, col_s2 = st.columns([1, 1])
            
            with col_s1:
                # O Termômetro Visual
                fig_gauge = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = score,
                    domain = {'x': [0, 1], 'y': [0, 1]},
                    title = {'text': "Termômetro da Saúde Financeira", 'font': {'size': 24}},
                    gauge = {
                        'axis': {'range': [None, 100]},
                        'bar': {'color': "white"},
                        'steps': [
                            {'range': [0, 40], 'color': "#EF553B"}, # Vermelho
                            {'range': [40, 70], 'color': "#FFA15A"}, # Laranja
                            {'range': [70, 100], 'color': "#00CC96"}] # Verde
                    }
                ))
                fig_gauge.update_layout(template="plotly_dark", height=300)
                st.plotly_chart(fig_gauge, use_container_width=True)
                
            with col_s2:
                st.markdown("### 🔍 Onde você está errando/acertando:")
                if entradas_s == 0:
                    st.warning("Adicione 'Entradas' neste mês para que eu possa fazer uma análise completa das suas despesas.")
                else:
                    if score >= 70:
                        st.success("✅ **Excelente!** Sua saúde financeira está em ótimo estado.")
                    elif score >= 40:
                        st.warning("⚠️ **Atenção!** Você está no limite. Cuidado com imprevistos.")
                    else:
                        st.error("🚨 **Crítico!** Suas finanças precisam de atenção imediata.")
                        
                    st.markdown("---")
                    
                    # Análise Detalhada por Categoria
                    gastos_cat = df_mes[df_mes['Tipo'] == 'Despesa'].groupby('Categoria')['Valor'].sum()
                    for cat, valor in gastos_cat.items():
                        percentual = (valor / entradas_s) * 100
                        if cat in ['Moradia', 'Alimentação'] and percentual > 50:
                            st.write(f"- 🔴 **{cat}:** Está consumindo {percentual:.1f}% da sua renda. O ideal para gastos fixos pesados é tentar não passar de 50% somados.")
                        elif cat == 'Lazer' and percentual > 20:
                            st.write(f"- 🟡 **{cat}:** {percentual:.1f}% da sua renda. Cuidado para o lazer não comprometer seus investimentos.")
                        elif percentual > 30:
                            st.write(f"- 🟡 **{cat}:** Atenção, {percentual:.1f}% da sua renda está indo apenas para esta categoria.")
                    
                    if despesas_s < entradas_s:
                        st.write("- 🟢 **Caixa:** Você não gastou tudo que ganhou. Ótimo hábito para construção de patrimônio!")

            st.markdown("---")
            st.subheader("🎖️ Suas Conquistas e Nível")
            
            # Cálculo de XP (Experiência baseada no uso do app)
            total_transacoes = len(df_saude)
            total_investimentos = len(buscar_investimentos(usuario))
            nivel = 1 + ((total_transacoes + (total_investimentos * 5)) // 15)
            
            st.write(f"**🌟 Nível Atual: {nivel}** (Continue lançando e investindo para subir!)")
            
            conquistas = []
            if total_investimentos > 0:
                conquistas.append("📈 **Visão de Águia:** Você começou a investir!")
            if not df_saude[(df_saude['Tipo'] == 'Despesa') & (df_saude['Data_dt'] < pd.to_datetime('today'))].empty:
                conquistas.append("📝 **Organizado:** Lançamentos em dia.")
            if score >= 80:
                conquistas.append("👑 **Mão de Ferro:** Score excelente neste mês.")
                
            if conquistas:
                for c in conquistas:
                    st.markdown(c)
            else:
                st.write("Complete meses no azul e invista para desbloquear medalhas!")
        else:
            st.info("Registre transações para visualizar o seu Raio-X.")
