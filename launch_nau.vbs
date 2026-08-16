Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
venvPython = scriptDir & "\.venv\Scripts\pythonw.exe"

' Prefer the copy a previous run left named for this app. Windows takes what it
' shows about a process -- the Details tab's name, the Processes tab's
' description, the icon beside it -- from the file the process was started from,
' so a plain pythonw.exe arrives as one more anonymous "Python" among every
' other Python app on the machine. app_support.process_identity makes a copy
' that says Nau instead, and this picks it up; the run makes it for the run
' after, so a checkout that has never started launches exactly as it used to.
namedPython = scriptDir & "\.venv\Scripts\Nau-Nau.exe"
If fso.FileExists(namedPython) Then venvPython = namedPython

If fso.FileExists(venvPython) Then
  cmd = """" & venvPython & """ -m nau"
Else
  cmd = "pythonw -m nau"
End If

shell.CurrentDirectory = scriptDir
shell.Run cmd, 0, False
