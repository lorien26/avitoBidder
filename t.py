import requests
def get_bid_info(token: str, item_id: int):
    url = f"https://api.avito.ru/cpxpromo/1/getBids/{item_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            print(response.json())
            return response.json()
        else:
            print(f"❌ Ошибка получения информации о ставках: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при получении информации о ставках: {e}")
        return None

get_bid_info("emocmz04Rq6UZtD-TsZ34w5GR4NZ7fMOFz7KLwPf", 7579176863)