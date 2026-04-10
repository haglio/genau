Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
venvPython = scriptDir & "\.venv\Scripts\pythonw.exe"

If fso.FileExists(venvPython) Then
  cmd = """" & venvPython & """ -m nau"
Else
  cmd = "pythonw -m nau"
End If

shell.CurrentDirectory = scriptDir
shell.Run cmd, 0, False
