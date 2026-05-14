import schedule
import time
import subprocess

def rodar_monitor():
    print("\n⏰ Iniciando varredura...")
    subprocess.run(["py", "monitor.py"])

schedule.every(30).minutes.do(rodar_monitor)

print("🚀 Monitor Daikin iniciado! Rodando a cada 30 minutos.")
print("   Pressione Ctrl+C para parar.\n")

rodar_monitor()

while True:
    schedule.run_pending()
    time.sleep(1)