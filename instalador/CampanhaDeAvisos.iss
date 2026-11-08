; Instalador da Campanha de Avisos
;
; Instala em %LOCALAPPDATA%: nao pede administrador, e a pasta e gravavel, porque
; o registro de quem foi avisado fica ao lado do programa. A desinstalacao NAO
; apaga dados\ nem saida\: sao a prova do que foi enviado.
;
; Nada de campanha vai no instalador: nem planilha, nem banco, nem sessao do
; WhatsApp. Cada computador comeca vazio, com os modelos de instalador\modelo.

#define Nome    "Campanha de Avisos"
#define Versao  "1.0.0"
#define Empresa "Sua Empresa"
#define Exe     "CampanhaDeAvisos.exe"

[Setup]
; AppId: identificador fixo do instalador. Gere o SEU (Inno Setup: Tools > Generate GUID)
; antes do primeiro build e nunca mais o troque: e por ele que a proxima versao
; atualiza a anterior.
AppId={{TROQUE-PELO-GUID-DO-SEU-INSTALADOR}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher={#Empresa}
VersionInfoVersion={#Versao}
VersionInfoCompany={#Empresa}
DefaultDirName={localappdata}\Programs\CampanhaDeAvisos
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=CampanhaDeAvisos-Instalador-{#Versao}
SetupIconFile=..\disparo\ui\icone.ico
UninstallDisplayIcon={app}\{#Exe}
UninstallDisplayName={#Nome}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Criar atalho na area de trabalho"

[Files]
Source: "..\dist\CampanhaDeAvisos\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Configuracao e textos: uma atualizacao nunca sobrescreve o que foi ajustado.
Source: "..\config.example.toml"; DestDir: "{app}"; DestName: "config.toml"; Flags: onlyifdoesntexist
Source: "modelo\teste_interno.modelo.txt"; DestDir: "{app}"; DestName: "teste_interno.csv"; Flags: onlyifdoesntexist
Source: "modelo\nao_enviar.modelo.txt"; DestDir: "{app}"; DestName: "nao_enviar.txt"; Flags: onlyifdoesntexist
Source: "modelo\mensagens\*"; DestDir: "{app}\mensagens"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{userdesktop}\{#Nome}"; Filename: "{app}\{#Exe}"; Tasks: atalho

[Run]
Filename: "{app}\{#Exe}"; Description: "Abrir a Campanha de Avisos"; Flags: nowait postinstall skipifsilent
