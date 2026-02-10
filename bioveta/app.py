import streamlit as st
import pandas as pd
import plotly.express as px
import re
from datetime import datetime

# --- КОНФИГУРАЦИЯ СТРАНИЦЫ ---
st.set_page_config(
    page_title="Market Access Gap Analysis",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS ДЛЯ СТИЛЯ ---
st.markdown("""
    <style>
    .block-container {padding-top: 2rem;}
    h1, h2, h3 {font-family: 'Helvetica Neue', sans-serif; color: #0F172A;}
    .metric-card {background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 15px; text-align: center;}
    .stDataFrame {border: 1px solid #E2E8F0; border-radius: 5px;}
    </style>
""", unsafe_allow_html=True)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def clean_text(text):
    if pd.isna(text): return ""
    return str(text).strip()

def parse_date_status(date_str):
    """Определяет статус лицензии/сертификата."""
    if pd.isna(date_str): return "Нет данных", None
    
    text = str(date_str).lower()
    if "истек" in text:
        return "Expired", None
    
    # Поиск даты DD.MM.YYYY
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', text)
    if match:
        try:
            date_obj = datetime.strptime(match.group(1), '%d.%m.%Y')
            if date_obj > datetime.now():
                return "Active", date_obj
            else:
                return "Expired", date_obj
        except:
            pass
    
    return "Unknown", None

def extract_drugs(drug_text):
    """Парсинг списка препаратов из одной ячейки."""
    if pd.isna(drug_text): return []
    
    text = str(drug_text)
    # Нормализация разделителей
    text = re.sub(r'\n', ';', text)
    text = re.sub(r'\d+\)', ';', text)
    text = re.sub(r'\d+\.', ';', text)
    
    drugs = [d.strip() for d in text.split(';') if len(d.strip()) > 2]
    return drugs

@st.cache_data
def process_single_file(uploaded_file):
    """Чтение 1-й и 3-й вкладки из одного Excel файла."""
    try:
        xls = pd.ExcelFile(uploaded_file)
        sheet_names = xls.sheet_names
        
        if len(sheet_names) < 1:
            return pd.DataFrame(), "Файл пуст или не содержит вкладок."
            
        # Логика: 1-я вкладка (index 0) = Отказы, 3-я вкладка (index 2) = Иностранные
        # Если вкладок меньше 3, пробуем взять 1-ю и 2-ю
        
        idx_refusal = 0
        idx_foreign = 2 if len(sheet_names) >= 3 else (1 if len(sheet_names) >= 2 else 0)
        
        if idx_foreign == 0 and len(sheet_names) == 1:
             return pd.DataFrame(), "В файле всего одна вкладка. Требуется минимум две (Отказы и Действующие)."

        # Читаем вкладки
        df_refusal = pd.read_excel(uploaded_file, sheet_name=idx_refusal)
        df_foreign = pd.read_excel(uploaded_file, sheet_name=idx_foreign)

    except Exception as e:
        return pd.DataFrame(), f"Ошибка чтения Excel: {str(e)}"

    # --- ОБРАБОТКА: АКТИВНЫЕ (Иностранные) ---
    col_drug_f = next((c for c in df_foreign.columns if 'перечень' in c.lower()), None)
    col_comp_f = next((c for c in df_foreign.columns if 'производител' in c.lower()), None)
    col_date_f = next((c for c in df_foreign.columns if 'срок' in c.lower()), None)

    valid_drugs_db = []
    
    if col_drug_f and col_comp_f:
        for _, row in df_foreign.iterrows():
            status, exp_date = parse_date_status(row[col_date_f] if col_date_f else None)
            company = clean_text(row[col_comp_f]).lower()
            drugs = extract_drugs(row[col_drug_f])
            
            for drug in drugs:
                valid_drugs_db.append({
                    'Company_Norm': company,
                    'Drug_Clean': drug.lower(),
                    'Drug_Original': drug,
                    'Status': status,
                    'Exp_Date': exp_date
                })
    
    df_valid_flat = pd.DataFrame(valid_drugs_db)

    # --- ОБРАБОТКА: ОТКАЗЫ ---
    col_drug_r = next((c for c in df_refusal.columns if 'перечень' in c.lower()), None)
    col_comp_r = next((c for c in df_refusal.columns if 'производител' in c.lower()), None)

    refusal_list = []
    
    if col_drug_r and col_comp_r:
        for _, row in df_refusal.iterrows():
            company = clean_text(row[col_comp_r])
            drugs = extract_drugs(row[col_drug_r])
            
            for drug in drugs:
                refusal_list.append({
                    'Company': company,
                    'Company_Norm': company.lower(),
                    'Refused_Drug': drug
                })
                
    df_refusal_flat = pd.DataFrame(refusal_list)

    # --- МАТЧИНГ ---
    results = []
    
    if not df_refusal_flat.empty and not df_valid_flat.empty:
        for _, r_row in df_refusal_flat.iterrows():
            r_comp = r_row['Company_Norm']
            r_drug = r_row['Refused_Drug'].lower()
            
            # 1. Фильтр по компании (первые 10 символов для нечеткого поиска)
            potential_matches = df_valid_flat[df_valid_flat['Company_Norm'].str.contains(r_comp[:10], regex=False, na=False)]
            
            match_status = "CRITICAL: Not Registered"
            match_details = "Not found in active list"
            
            if not potential_matches.empty:
                # 2. Фильтр по названию препарата (поиск подстроки)
                drug_match = potential_matches[potential_matches['Drug_Clean'].str.contains(r_drug[:10], regex=False, na=False)]
                
                if not drug_match.empty:
                    best_match = drug_match.iloc[0]
                    if best_match['Status'] == 'Active':
                        match_status = "OK: Registered"
                        match_details = f"Active until {best_match['Exp_Date'].strftime('%Y-%m-%d') if best_match['Exp_Date'] else 'Date OK'}"
                    else:
                        match_status = "WARNING: Expired"
                        match_details = "Found but certificate expired"
            
            results.append({
                'Manufacturer': r_row['Company'],
                'Drug Name (Refused)': r_row['Refused_Drug'],
                'Current Status': match_status,
                'Details': match_details
            })
    elif df_refusal_flat.empty:
        return pd.DataFrame(), "Не найдены данные в таблице отказов (проверьте 1-ю вкладку)."
    elif df_valid_flat.empty:
        return pd.DataFrame(), "Не найдены данные в таблице действующих (проверьте 3-ю вкладку)."
            
    return pd.DataFrame(results), None

# --- UI ПРИЛОЖЕНИЯ ---

st.title("Strategic Gap Analysis")
st.markdown("### Инструмент сверки реестров и анализа доступности")

with st.sidebar:
    st.header("Панель управления")
    uploaded_file = st.file_uploader("Загрузите файл с данными (Excel)", type=['xlsx', 'xls'])
    
    st.info(
        """
        **Алгоритм обработки:**
        1. Чтение 1-й вкладки (Архив отказов).
        2. Чтение 3-й вкладки (Действующие лицензии).
        3. Cross-check анализ номенклатуры.
        """
    )

if uploaded_file:
    with st.spinner('Анализ структуры данных и сопоставление...'):
        df_result, error_msg = process_single_file(uploaded_file)
        
    if error_msg:
        st.error(error_msg)
    elif df_result.empty:
        st.warning("Совпадений не найдено или структура файла не распознана.")
    else:
        # --- МЕТРИКИ ---
        col1, col2, col3 = st.columns(3)
        
        total = len(df_result)
        ok_count = len(df_result[df_result['Current Status'].str.contains("OK")])
        critical_count = len(df_result[~df_result['Current Status'].str.contains("OK")])
        
        col1.metric("Всего проанализировано", total)
        col2.metric("Активные позиции", ok_count, delta_color="normal")
        col3.metric("Требуют регистрации (Gaps)", critical_count, delta_color="inverse")
        
        # --- ТАБЛИЦЫ ---
        tab1, tab2 = st.tabs(["🔴 ACTION LIST (Приоритет)", "📊 Полный реестр"])
        
        with tab1:
            st.subheader("Action List: Требуют внимания")
            st.markdown("Позиции, по которым ранее был отказ и которые **отсутствуют** в текущем списке действующих.")
            
            df_critical = df_result[~df_result['Current Status'].str.contains("OK")]
            
            st.dataframe(
                df_critical.style.applymap(
                    lambda x: 'background-color: #ffcdd2' if 'CRITICAL' in str(x) else 'background-color: #fff9c4', 
                    subset=['Current Status']
                ),
                use_container_width=True,
                height=600
            )
            
            csv_data = df_critical.to_csv(index=False).encode('utf-8')
            st.download_button("Скачать отчет (CSV)", csv_data, "gap_analysis_report.csv", "text/csv")

        with tab2:
            st.dataframe(df_result, use_container_width=True)
            
        # --- ГРАФИК ---
        if not df_critical.empty:
            st.markdown("---")
            df_chart = df_critical['Manufacturer'].value_counts().head(10).reset_index()
            df_chart.columns = ['Производитель', 'Кол-во']
            
            fig = px.bar(
                df_chart, y='Производитель', x='Кол-во', orientation='h',
                title='Топ производителей по числу незакрытых позиций',
                color_discrete_sequence=['#ef5350']
            )
            fig.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Ожидание загрузки файла данных...")
