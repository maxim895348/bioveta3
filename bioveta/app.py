import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io

# --- НАСТРОЙКИ ---
st.set_page_config(page_title="GMP Gap Analysis", layout="wide")

# --- ФУНКЦИИ ---

def clean_text(text):
    if pd.isna(text): return ""
    return str(text).strip()

def extract_drugs(drug_text):
    """Парсинг ячейки с препаратами."""
    if pd.isna(drug_text): return []
    text = str(drug_text)
    # Убираем мусор и разбивку
    text = re.sub(r'\n', ';', text)
    text = re.sub(r'\d+\)', ';', text)
    text = re.sub(r'\d+\.', ';', text)
    # Разбиваем по точке с запятой или просто запятой, если нет ;
    if ';' not in text and ',' in text:
        text = text.replace(',', ';')
        
    return [d.strip() for d in text.split(';') if len(d.strip()) > 2]

def parse_date_status(date_str):
    if pd.isna(date_str): return "Нет данных", None
    text = str(date_str).lower()
    if "истек" in text: return "Expired", None
    
    # Ищем дату
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', text)
    if match:
        try:
            date_obj = datetime.strptime(match.group(1), '%d.%m.%Y')
            return ("Active", date_obj) if date_obj > datetime.now() else ("Expired", date_obj)
        except: pass
    return "Unknown", None

def find_header_row(df, keyword="перечень"):
    """Ищет строку, в которой встречается ключевое слово."""
    # Сканируем первые 20 строк
    for i in range(min(20, len(df))):
        row_str = df.iloc[i].astype(str).str.lower().to_string()
        if keyword in row_str:
            return i
    return None

def load_data_from_sheet(uploaded_file, sheet_name):
    """Загружает конкретный лист и находит заголовок."""
    try:
        # 1. Читаем "сырой" лист
        if uploaded_file.name.endswith('.csv'):
             # CSV обычно один лист, игнорируем sheet_name
             df = pd.read_csv(uploaded_file)
        else:
             df = pd.read_excel(uploaded_file, sheet_name=sheet_name, header=None)
        
        # 2. Ищем строку с заголовками (ищем слово 'перечень' или 'производител')
        header_idx = find_header_row(df, "перечень")
        if header_idx is None:
            header_idx = find_header_row(df, "производител")
            
        if header_idx is not None:
            # Перезагружаем с правильным заголовком
            # Для Excel это просто чтение с header=...
            # Для DataFrame делаем срез
            df.columns = df.iloc[header_idx]
            df = df.iloc[header_idx+1:].reset_index(drop=True)
            return df, None
        else:
            return df, "Не удалось найти строку заголовков (слова 'Перечень' или 'Производитель')."
            
    except Exception as e:
        return None, str(e)

# --- ИНТЕРФЕЙС ---

st.title("🛡️ GMP Gap Analysis Tool")
st.markdown("Загрузите один Excel-файл, выберите вкладки, и система найдет разрывы.")

# 1. ЗАГРУЗКА
uploaded_file = st.file_uploader("Загрузить файл (.xls, .xlsx)", type=['xls', 'xlsx'])

if uploaded_file:
    # Читаем названия листов
    xls = pd.ExcelFile(uploaded_file)
    sheet_names = xls.sheet_names
    
    st.markdown("---")
    c1, c2 = st.columns(2)
    
    # 2. ВЫБОР ЛИСТОВ (По умолчанию пытаемся угадать)
    default_ref = next((i for i, s in enumerate(sheet_names) if 'отказ' in s.lower()), 0)
    # Для второго листа берем индекс 2 (обычно 3-я вкладка), если есть, иначе 1
    default_act = 2 if len(sheet_names) > 2 else (1 if len(sheet_names) > 1 else 0)
    
    with c1:
        st.info("Где список ОТКАЗОВ?")
        sheet_ref = st.selectbox("Выберите вкладку с отказами:", sheet_names, index=default_ref)
        
    with c2:
        st.info("Где список ДЕЙСТВУЮЩИХ?")
        sheet_act = st.selectbox("Выберите вкладку с действующими:", sheet_names, index=default_act)

    if st.button("🚀 ЗАПУСТИТЬ АНАЛИЗ", type="primary"):
        with st.spinner("Сканирование данных..."):
            
            # ЗАГРУЗКА ДАННЫХ
            df_refusal, err_r = load_data_from_sheet(uploaded_file, sheet_ref)
            df_active, err_a = load_data_from_sheet(uploaded_file, sheet_act)
            
            if err_r: st.error(f"Ошибка в листе отказов: {err_r}")
            elif err_a: st.error(f"Ошибка в листе действующих: {err_a}")
            else:
                # ПОИСК КОЛОНОК
                col_drug_r = next((c for c in df_refusal.columns if 'перечень' in str(c).lower()), None)
                col_comp_r = next((c for c in df_refusal.columns if 'производител' in str(c).lower()), None)
                
                col_drug_a = next((c for c in df_active.columns if 'перечень' in str(c).lower()), None)
                col_comp_a = next((c for c in df_active.columns if 'производител' in str(c).lower()), None)
                
                if not (col_drug_r and col_comp_r and col_drug_a and col_comp_a):
                    st.error(f"""
                    Не найдены нужные колонки!
                    Программа ищет колонки, содержащие слова 'Производитель' и 'Перечень'.
                    
                    Найдены колонки в отказах: {list(df_refusal.columns)}
                    Найдены колонки в действующих: {list(df_active.columns)}
                    """)
                else:
                    # --- АНАЛИТИКА ---
                    
                    # 1. Собираем базу активных
                    active_db = []
                    col_date_a = next((c for c in df_active.columns if 'срок' in str(c).lower()), None)
                    
                    for _, row in df_active.iterrows():
                        comp = clean_text(row[col_comp_a]).lower()
                        status, dt = parse_date_status(row[col_date_a] if col_date_a else None)
                        drugs = extract_drugs(row[col_drug_a])
                        for d in drugs:
                            active_db.append({'Comp': comp, 'Drug': d.lower(), 'Status': status, 'Date': dt})
                    
                    df_db = pd.DataFrame(active_db)
                    
                    # 2. Проверяем отказы
                    results = []
                    for _, row in df_refusal.iterrows():
                        comp_orig = clean_text(row[col_comp_r])
                        comp_norm = comp_orig.lower()
                        drugs = extract_drugs(row[col_drug_r])
                        
                        for d in drugs:
                            final_status = "CRITICAL: Not Registered"
                            details = "Not found"
                            
                            # Поиск в базе
                            if not df_db.empty:
                                # Фильтр по компании (первые 15 символов)
                                matches = df_db[df_db['Comp'].str.contains(comp_norm[:15], regex=False, na=False)]
                                if not matches.empty:
                                    # Фильтр по препарату (поиск подстроки)
                                    d_matches = matches[matches['Drug'].str.contains(d.lower()[:10], regex=False, na=False)]
                                    if not d_matches.empty:
                                        best = d_matches.iloc[0]
                                        if best['Status'] == 'Active':
                                            final_status = "OK: Registered"
                                            details = f"Active until {best['Date'].strftime('%d.%m.%Y') if best['Date'] else 'OK'}"
                                        else:
                                            final_status = "WARNING: Expired"
                                            details = "Expired found"
                            
                            results.append({
                                'Производитель': comp_orig,
                                'Препарат (Отказ)': d,
                                'Статус сейчас': final_status,
                                'Детали': details
                            })
                            
                    df_res = pd.DataFrame(results)
                    
                    # --- ВЫВОД РЕЗУЛЬТАТОВ ---
                    
                    crit = df_res[~df_res['Статус сейчас'].str.contains("OK")]
                    
                    st.success("Анализ завершен!")
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Всего позиций в отказах", len(df_res))
                    m2.metric("Сейчас активны", len(df_res) - len(crit))
                    m3.metric("ТРЕБУЮТ РЕГИСТРАЦИИ", len(crit), delta_color="inverse")
                    
                    st.markdown("### 🔴 Action List (Что нужно дорегистрировать)")
                    st.dataframe(
                        crit.style.applymap(lambda x: 'background-color: #ffcdd2', subset=['Статус сейчас']),
                        use_container_width=True
                    )
                    
                    # Скачивание
                    csv = crit.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        "📥 Скачать отчет (Excel/CSV)",
                        csv,
                        "gap_analysis.csv",
                        "text/csv",
                        type="primary"
                    )
                    
                    with st.expander("Показать полный список (включая успешные)"):
                        st.dataframe(df_res)

else:
    st.info("Жду файл...")
