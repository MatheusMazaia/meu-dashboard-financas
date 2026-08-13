import streamlit as st
import pandas as pd
import plotly.express as px
import psycopg2
from psycopg2 import IntegrityError
import hashlib
from datetime import datetime
import calendar

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Maza Finance", layout="wide")

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

# --- ATUALIZAÇÃO DO BANCO (MIGRAÇÕES AUTOMÁTICAS) ---
def check_and_add_column(table, column, col_type, default_val):
    c.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' and column_name='{column}'")
    if not c.fetchone():
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default_val}'")

check_and_add_column('transacoes', 'conta', 'VARCHAR(255)', 'Geral')
check_and_add_column('transacoes', 'status', 'VARCHAR(50)', 'Pago')
# NOVO: Coluna para Forma de Pagamento
check_and_add_column('transacoes', 'forma_pagamento', 'VARCHAR(50)', 'Débito')

# --- FUNÇÕES DE SEGURANÇA E BANCO ---
def gerar_hash(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

def adicionar_usuario(usuario, senha):
    c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s, %s)", (usuario, gerar_hash(senha)))

def verificar_login(usuario, senha):
    c.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, gerar_hash(senha)))
    return c.fetchone()

# Atualizado com forma_pagamento
def adicionar_transacao(usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("INSERT INTO transacoes (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", 
              (usuario, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento))

def buscar_transacoes(usuario):
    c.execute("SELECT id, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento FROM transacoes WHERE usuario = %s", (usuario,))
    dados = c.fetchall()
    return pd.DataFrame(dados, columns=['ID', 'Data', 'Tipo', 'Categoria', 'Valor', 'Descrição', 'Conta', 'Status', 'Forma de Pagamento'])

def deletar_transacao(id_transacao):
    c.execute("DELETE FROM transacoes WHERE id = %s", (id_transacao,))

# Atualizado com forma_pagamento
def atualizar_transacao(id_transacao, data, tipo, categoria, valor, descricao, conta, status, forma_pagamento):
    c.execute("UPDATE transacoes SET data=%s, tipo=%s, categoria=%s, valor=%s, descricao=%s, conta=%s, status=%s, forma_pagamento=%s WHERE id=%s", 
              (data, tipo, categoria, valor, descricao, conta, status, forma_pagamento, id_transacao))

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
    st.title("Bem-vindo ao Maza Finance")
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
    
    st.sidebar.title(f"👤 Olá, {usuario}")
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['logado'] = False
        st.session_state['usuario_atual'] = ""
        st.rerun()
        
    st.sidebar.markdown("---")
    
    aba_lancamento, aba_investimento = st.sidebar.tabs(["💸 Lançamento", "📈 Investimento"])
    
    with aba_lancamento:
        tipo_lancamento = st.selectbox("Tipo", ["Despesa", "Entrada"], key="tipo_lanc")
        if tipo_lancamento == "Despesa":
            categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros"], key="cat_lanc")
        else:
            categoria = st.selectbox("Categoria", ["Salário", "Freelance", "Rendimento", "Outros"], key="cat_lanc")
            
        conta_lancamento = st.selectbox("Conta / Instituição", ["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Outra"], key="conta_lanc")
        
        # NOVO: Forma de Pagamento
        forma_pagamento = st.selectbox("Forma de Pagamento", ["Pix", "Débito", "Crédito"], key="forma_pag")
        
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

    with aba_investimento:
        tipo_inv = st.selectbox("Tipo de Investimento", ["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "Fundos Imobiliários (FIIs)", "Criptomoedas", "Previdência", "Outros"])
        data_inv = st.date_input("Data da Aplicação", datetime.today(), format="DD/MM/YYYY", key="data_inv")
        valor_inv = st.number_input("Valor Investido (R$)", min_value=0.01, format="%.2f", key="valor_inv")
        desc_inv = st.text_input("Descrição (Ex: CDB Itaú, PETR4)", key="desc_inv")
        
        if st.button("Salvar Investimento", type="primary", use_container_width=True):
            adicionar_investimento(usuario, str(data_inv), tipo_inv, valor_inv, desc_inv)
            st.success("Investimento salvo!")
            st.rerun()

    st.sidebar.markdown("---")
    
    with st.sidebar.expander("🎯 Definir Meta de Gastos"):
        cat_meta = st.selectbox("Categoria", ["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Outros"], key="cat_meta2")
        valor_meta = st.number_input("Limite (R$)", min_value=1.0, format="%.2f", key="val_meta2")
        if st.button("Salvar Meta"):
            salvar_meta(usuario, cat_meta, valor_meta)
            st.success(f"Meta de {cat_meta} salva!")
            st.rerun()

    # --- CORPO DO DASHBOARD ---
    st.title("📊 Seu Dashboard Financeiro")
    
    aba_visao_geral, aba_carteira = st.tabs(["💰 Fluxo de Caixa", "💼 Meus Investimentos"])
    
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
                
            st.subheader("📈 Evolução de Receitas e Despesas")
            df_linha = df.copy()
            df_linha['Mes_Data'] = df_linha['Data_dt'].dt.to_period('M').dt.to_timestamp()
            resumo_linha = df_linha.groupby(['Mes_Data', 'Tipo'])['Valor'].sum().reset_index()
            
            fig_linha = px.line(resumo_linha, x='Mes_Data', y='Valor', color='Tipo', markers=True,
                                template="plotly_dark", color_discrete_map={'Entrada': '#00CC96', 'Despesa': '#EF553B'})
            fig_linha.update_xaxes(title="", tickformat="%m/%Y", dtick="M1")
            st.plotly_chart(fig_linha, use_container_width=True)
            
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
                
                st.subheader("🎯 Suas Metas Mensais")
                metas = buscar_metas(usuario)
                if metas and mes_selecionado != "Todos os Meses":
                    for cat, limite in metas.items():
                        gasto_cat = df_filtrado[(df_filtrado['Tipo'] == 'Despesa') & (df_filtrado['Categoria'] == cat)]['Valor'].sum()
                        pct = gasto_cat / limite if limite > 0 else 0
                        
                        st.write(f"**{cat}**: Gasto R\${gasto_cat:.2f} de R\${limite:.2f}")
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
                
                df_despesas = df_filtrado[df_filtrado['Tipo'] == 'Despesa']
                
                # NOVO: Gráfico de Formas de Pagamento
                with st.expander("💳 Formas de Pagamento (Pix, Débito, Crédito)", expanded=True):
                    if not df_despesas.empty:
                        resumo_pag = df_despesas.groupby('Forma de Pagamento')['Valor'].sum().reset_index()
                        fig_pag = px.pie(resumo_pag, values='Valor', names='Forma de Pagamento', hole=0.4, template="plotly_dark")
                        st.plotly_chart(fig_pag, use_container_width=True)
                    else:
                        st.write("Sem despesas registradas para analisar as formas de pagamento.")

                with st.expander("📊 Visão de Contas (Bancos)", expanded=False):
                    resumo_contas = df_filtrado.groupby(['Conta', 'Tipo'])['Valor'].sum().reset_index()
                    fig_contas = px.bar(resumo_contas, x='Conta', y='Valor', color='Tipo', barmode='group', template="plotly_dark",
                                        color_discrete_map={'Entrada': '#00CC96', 'Despesa': '#EF553B'}, text_auto='.2f')
                    st.plotly_chart(fig_contas, use_container_width=True)

                with st.expander("📉 Visão de Despesas por Categoria", expanded=False):
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
                            
                st.markdown("---")
                
                st.subheader("📋 Extrato Detalhado")
                
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
                        "Categoria": st.column_config.SelectboxColumn("Categoria", options=["Alimentação", "Transporte", "Viagens", "Moradia", "Lazer", "Saúde", "Educação", "Salário", "Freelance", "Rendimento", "Outros"]),
                        "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0),
                        "Conta": st.column_config.SelectboxColumn("Conta", options=["Nubank", "Itaú", "Inter", "Bradesco", "Santander", "Caixa", "Banco do Brasil", "Dinheiro", "Outra"]),
                        "Forma de Pagamento": st.column_config.SelectboxColumn("Forma de Pagamento", options=["Pix", "Débito", "Crédito"]),
                        "Status": st.column_config.SelectboxColumn("Status", options=["Pago", "Pendente"])
                    }
                )
                
                csv_dados = df_editavel.to_csv(index=False, sep=';').encode('utf-8-sig')
                nome_arquivo = f"extrato_{mes_selecionado.replace('/', '_')}.csv" if mes_selecionado != "Todos os Meses" else "extrato_completo.csv"
                st.download_button(label="📥 Baixar Planilha", data=csv_dados, file_name=nome_arquivo, mime="text/csv")
                
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

    with aba_carteira:
        st.subheader("💼 Meu Patrimônio Acumulado")
        df_inv = buscar_investimentos(usuario)
        
        if df_inv.empty:
            st.info("Você ainda não tem investimentos cadastrados. Use o menu lateral na aba '📈 Investimento' para começar a investir!")
        else:
            total_investido = df_inv['Valor'].sum()
            st.metric("Total Investido", f"R$ {total_investido:,.2f}")
            
            col_inv1, col_inv2 = st.columns([1, 1])
            with col_inv1:
                resumo_inv = df_inv.groupby('Tipo')['Valor'].sum().reset_index()
                fig_inv = px.pie(resumo_inv, values='Valor', names='Tipo', hole=0.4, template="plotly_dark", title="Diversificação da Carteira")
                st.plotly_chart(fig_inv, use_container_width=True)
            
            with col_inv2:
                st.markdown("**Gerenciar Aplicações**")
                df_inv_editavel = df_inv.copy()
                df_inv_editavel['Data'] = pd.to_datetime(df_inv_editavel['Data']).dt.date
                
                mudancas_inv = st.data_editor(
                    df_inv_editavel,
                    hide_index=True,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="editor_inv",
                    column_config={
                        "ID": st.column_config.NumberColumn("ID", disabled=True),
                        "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                        "Tipo": st.column_config.SelectboxColumn("Tipo", options=["Renda Fixa (CDB/LCI)", "Tesouro Direto", "Ações", "Fundos Imobiliários (FIIs)", "Criptomoedas", "Previdência", "Outros"]),
                        "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0)
                    }
                )
                
                if "editor_inv" in st.session_state:
                    if st.session_state["editor_inv"]["deleted_rows"]:
                        if st.button("🗑️ Deletar Investimentos Selecionados", type="primary"):
                            for row_idx in st.session_state["editor_inv"]["deleted_rows"]:
                                id_del = int(df_inv_editavel.iloc[row_idx]["ID"])
                                deletar_investimento(id_del)
                            st.success("Investimento(s) removido(s)!")
                            st.rerun()
