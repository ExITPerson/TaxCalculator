import schedule
import time

def test_job():
    print("Тестовая задача сработала!")

# Ставим на ближайшую минуту
schedule.every(1).minutes.do(test_job)
print("Планировщик запущен. Ждем 1 минуту...")

# Ждем 70 секунд
end = time.time() + 70
while time.time() < end:
    schedule.run_pending()
    time.sleep(1)