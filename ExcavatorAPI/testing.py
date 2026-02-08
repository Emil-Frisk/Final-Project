import threading
from time import sleep

exit=False

def test_loop():
    global exit
    while not exit:
        sleep(3)
    print("test loop exited")

thr=threading.Thread(target=test_loop, daemon=True)
thr.start()

print("exit flag flipped")
exit=True
print("starting to join")
thr.join(5)
print("finished join")