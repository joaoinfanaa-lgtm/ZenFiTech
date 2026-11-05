# ZenFi para Android (.apk) — com microfone

Projeto Android pronto: um app que abre o seu site do ZenFi em tela cheia, guarda o login, libera o **microfone** e traz o **reconhecimento de voz nativo** do Android para o Assistente de voz.
Não usa Node nem bibliotecas externas.

## 1) Antes de tudo (1 minuto)
Abra `app/src/main/res/values/strings.xml` e troque `https://SEU-APP.onrender.com` pelo endereço real do seu site (precisa ser **https**).

## 2) Gerar o .apk — escolha UM jeito

### Jeito fácil, sem instalar nada: pelo GitHub
1. Suba **toda a pasta do projeto** (inclusive `android-app/` e `.github/`) para o seu repositório.
2. No GitHub: aba **Actions → Gerar APK Android → Run workflow**.
3. Quando terminar (uns 5 min), abra a execução e baixe **ZenFi-apk** (contém `app-debug.apk`).
4. Mande o arquivo para o celular e instale (o Android pede para permitir "instalar apps desconhecidos").

### Jeito com Android Studio
1. Abra o Android Studio → **Open** → escolha a pasta `android-app`.
2. Espere o *Gradle sync* (ele baixa o que precisa; aceite as licenças se pedir).
3. **Build → Build Bundle(s) / APK(s) → Build APK(s)** → clique em *locate*.
   Ou ligue o celular por cabo (depuração USB) e aperte ▶ **Run**.

## 3) Usar o microfone
Na primeira vez que tocar no 🎤 o Android pergunta **"Permitir que o ZenFi grave áudio?"** → **Permitir**.
Se negou sem querer: Configurações → Apps → ZenFi → Permissões → Microfone.
O aparelho precisa ter o app **Google** (reconhecimento de voz) instalado e atualizado; o ditado pelo teclado também continua funcionando como alternativa.

## 4) Publicar na Google Play
O `.apk` acima é de teste (assinado com chave de depuração). Para a loja:
1. Crie um keystore: `keytool -genkey -v -keystore zenfi.jks -alias zenfi -keyalg RSA -keysize 2048 -validity 10000` (**guarde o arquivo e as senhas**: sem eles você não consegue atualizar o app).
2. Android Studio → **Build → Generate Signed Bundle / APK → Android App Bundle (.aab)**.
3. Na Google Play Console: conta de desenvolvedor (taxa única de US$ 25), política de privacidade publicada (o ZenFi guarda dados financeiros e usa microfone) e a declaração de uso do microfone.

## Como funciona / limites (leia)
- O app é uma "moldura" do site: toda atualização que você publicar no Render aparece no app sem gerar novo .apk.
- Sem internet aparece uma tela "Sem conexão" com botão para tentar de novo.
- Links para outros sites abrem no navegador. Permissão de microfone só é concedida ao endereço do ZenFi.
- Downloads de arquivos feitos pela página (ex.: exportar backup) **não** são tratados pelo WebView; importar arquivo funciona.
- O texto falado cai na tela do Assistente de voz, onde você confere e confirma. No WhatsApp o lançamento é automático.
- Ícone: gerado a partir do `icon-maskable.png`; para trocar, substitua os `ic_launcher.png` em `app/src/main/res/mipmap-*`.
- **Este projeto foi escrito e revisado, mas não compilado aqui** (o ambiente onde ele foi criado não tem Android SDK nem internet). A ponte de voz em JavaScript foi testada; a parte Java/Gradle não. Se o build acusar erro, me mande a mensagem completa que eu corrijo.
