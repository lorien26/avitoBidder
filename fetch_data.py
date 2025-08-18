import json
import tabnanny
import time
from curl_cffi import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def fetch_and_save_to_json(url, filename='fetch.json', timeout=30, retries=3):
    # Создаем сессию с настройками
    session = requests.Session()
    
    # Настраиваем retry стратегию

    
    # Настраиваем заголовки для имитации браузера
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        print(f"Выполняю GET запрос к: {url}")
        start_time = time.time()
        
        # Выполняем запрос
        response = session.get(
            url, 
            headers=headers, 
            timeout=timeout,
            impersonate="chrome"  # Используем curl_cffi для обхода блокировок
        )
        
        request_time = time.time() - start_time
        print(f"Запрос выполнен за {request_time:.2f} секунд")
        print(f"Статус ответа: {response.status_code}")
        
        # Проверяем статус ответа
        response.raise_for_status()
        
        # Пытаемся получить JSON
        try:
            data = response.json()
            print("Получен JSON ответ")
        except json.JSONDecodeError:
            # Если не JSON, сохраняем как есть
            print("Получен не-JSON ответ, сохраняю как raw data")
            data = response.text
            
            data = find_json_on_page(html_code=data)
            print(type(data))
            print(type(data))
            print(type(data))
            print(type(data))
        # Добавляем метаданные
        if isinstance(data, dict):
            data['_metadata'] = {
                'url': url,
                'status_code': response.status_code,
                'request_time': request_time,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'content_length': len(response.content)
            }
        
        # Сохраняем в файл
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"Данные успешно сохранены в файл {filename}")
        return data
        
    except requests.exceptions.Timeout:
        print(f"Ошибка: Таймаут запроса ({timeout} секунд)")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return None
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")
        return None
    finally:
        session.close()
from bs4 import BeautifulSoup
import html
def find_json_on_page(html_code, data_type: str = "mime") -> dict:
        soup = BeautifulSoup(html_code, "html.parser")
        try:
            for _script in soup.select('script'):
                if data_type == 'mime':
                    if _script.get('type') == 'mime/invalid' and _script.get(
                            'data-mfe-state') == 'true':  # and 'sandbox' not in _script.text:
                        mime_data = json.loads(html.unescape(_script.text)).get('data', {})
                        return mime_data

        except Exception as err:
            print(err)
        return {}

def read_html_file(filename='m.html'):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            html_content = f.read()
        print(f"HTML файл {filename} успешно загружен")
        return html_content
    except FileNotFoundError:
        print(f"HTML файл {filename} не найден")
        return None
    except Exception as e:
        print(f"Ошибка при чтении HTML файла {filename}: {e}")
        return None

def main():
    """Основная функция для демонстрации"""
    # Пример URL для тестирования
    test_url = "https://www.avito.ru/moskva/muzykalnye_instrumenty/bubny_shamanskie_desyatki_vidov_kazhdyy_s_dushoy_7409894879"
    
    result = fetch_and_save_to_json(test_url, 'fetch.json')
    # t = read_html_file('m.html')
    # print(t)
    # result = find_json_on_page(html_code=t)
    print(result)
    if result:
        print("Результат запроса получен успешно!")
        print(f"Тип данных: {type(result)}")
        if isinstance(result, dict):
            print(f"Ключи: {list(result.keys())}")
    else:
        print("Не удалось получить данные")

if __name__ == "__main__":
    main()
