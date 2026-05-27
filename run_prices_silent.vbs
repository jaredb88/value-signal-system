' run_prices_silent.vbs
' Lanza run_prices.bat de forma totalmente invisible (sin ventana CMD)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\value-signal-local\repo\run_prices.bat""", 0, False
