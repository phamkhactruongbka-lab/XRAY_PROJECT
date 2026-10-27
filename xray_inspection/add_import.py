with open('tests/test_roi_mic_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()
if 'import ultralytics' not in c:
    c = 'import ultralytics  # noqa: F401\n' + c
    with open('tests/test_roi_mic_integration.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print('Added ultralytics import to test_roi_mic_integration.py')
else:
    print('Already present')

