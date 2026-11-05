package com.zenfi.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.util.ArrayList;

/**
 * ZenFi para Android: abre o site dentro de um WebView e liga o microfone.
 *  - getUserMedia (microfone da página) é liberado só para o endereço do ZenFi;
 *  - o WebView não tem reconhecimento de voz próprio, então criamos aqui a ponte
 *    window.Capacitor.Plugins.SpeechRecognition, que o Assistente de voz do ZenFi já sabe usar.
 */
public class MainActivity extends Activity {
    private static final int REQ_MIC = 10, REQ_ARQUIVO = 11;

    // Ponte de voz injetada na página: mesma interface do plugin @capacitor-community/speech-recognition
    private static final String SHIM =
        "(function(){if(window.__zenVoz||!window.ZenNativo)return;var p={};"
        + "window.__zenVoz={"
        + "perm:function(ok){var x=p.perm;p.perm=null;if(x){ok?x.res():x.rej(new Error('permissao'));}},"
        + "fim:function(t,e){var x=p.start;p.start=null;if(!x)return;t?x.res({matches:[t]}):x.rej(new Error(e||'sem fala'));}};"
        + "window.Capacitor=window.Capacitor||{};window.Capacitor.Plugins=window.Capacitor.Plugins||{};"
        + "window.Capacitor.Plugins.SpeechRecognition={"
        + "requestPermissions:function(){return new Promise(function(res,rej){"
        + "if(ZenNativo.temPermissao()){res();return;}p.perm={res:res,rej:rej};ZenNativo.pedirPermissao();});},"
        + "start:function(o){return new Promise(function(res,rej){p.start={res:res,rej:rej};"
        + "ZenNativo.iniciar((o&&o.language)||'pt-BR');});},"
        + "stop:function(){ZenNativo.parar();return Promise.resolve();}};})();";

    private WebView web;
    private SpeechRecognizer reconhecedor;
    private boolean pedindoParaVoz = false;
    private PermissionRequest permissaoWeb;
    private ValueCallback<Uri[]> seletor;
    private String urlApp, host;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        urlApp = getString(R.string.zenfi_url);
        host = Uri.parse(urlApp).getHost();
        getWindow().setStatusBarColor(Color.parseColor("#04120C"));
        getWindow().setNavigationBarColor(Color.parseColor("#04120C"));

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#04120C"));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);                    // localStorage do app (cópia local dos dados)
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setUserAgentString(s.getUserAgentString() + " ZenFiApp/1.0");
        CookieManager.getInstance().setAcceptCookie(true);   // login por cookie

        web.addJavascriptInterface(new Nativo(), "ZenNativo");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (host != null && host.equalsIgnoreCase(u.getHost())) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignorada) { }
                return true;                              // links de fora abrem no navegador, não aqui dentro
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                v.evaluateJavascript(SHIM, null);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) v.loadUrl("file:///android_asset/offline.html");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest req) {
                runOnUiThread(() -> {
                    boolean audio = false;
                    for (String r : req.getResources())
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r)) audio = true;
                    boolean nosso = host != null && host.equalsIgnoreCase(req.getOrigin().getHost());
                    if (!audio || !nosso) { req.deny(); return; }
                    if (temMic()) {
                        req.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                    } else {
                        permissaoWeb = req;
                        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                    }
                });
            }

            @Override
            public boolean onShowFileChooser(WebView w, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (seletor != null) seletor.onReceiveValue(null);
                seletor = cb;
                try {
                    startActivityForResult(p.createIntent(), REQ_ARQUIVO);
                } catch (Exception e) {
                    seletor = null;
                    return false;
                }
                return true;
            }
        });

        if (b != null) web.restoreState(b); else web.loadUrl(urlApp);
    }

    private boolean temMic() {
        return checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    private void js(String codigo) {
        web.evaluateJavascript(codigo, null);
    }

    private void fim(String texto, String erro) {
        js("window.__zenVoz&&window.__zenVoz.fim(" + (texto == null ? "null" : JSONObject.quote(texto))
                + "," + JSONObject.quote(erro == null ? "" : erro) + ")");
    }

    private void iniciarVoz(String idioma) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) { fim(null, "indisponivel"); return; }
        if (!temMic()) { fim(null, "permissao"); return; }
        if (reconhecedor != null) reconhecedor.destroy();
        reconhecedor = SpeechRecognizer.createSpeechRecognizer(this);
        reconhecedor.setRecognitionListener(new RecognitionListener() {
            @Override public void onResults(Bundle r) {
                ArrayList<String> l = r.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                fim(l != null && !l.isEmpty() ? l.get(0) : null, "sem fala");
            }
            @Override public void onError(int codigo) { fim(null, "erro " + codigo); }
            @Override public void onReadyForSpeech(Bundle p) { }
            @Override public void onBeginningOfSpeech() { }
            @Override public void onRmsChanged(float v) { }
            @Override public void onBufferReceived(byte[] buf) { }
            @Override public void onEndOfSpeech() { }
            @Override public void onPartialResults(Bundle p) { }
            @Override public void onEvent(int t, Bundle p) { }
        });
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, idioma);
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        reconhecedor.startListening(i);
    }

    /** Funções que a página chama (window.ZenNativo). */
    private class Nativo {
        @JavascriptInterface public boolean temPermissao() { return temMic(); }

        @JavascriptInterface public void pedirPermissao() {
            runOnUiThread(() -> {
                pedindoParaVoz = true;
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
            });
        }

        @JavascriptInterface public void iniciar(final String idioma) { runOnUiThread(() -> iniciarVoz(idioma)); }

        @JavascriptInterface public void parar() {
            runOnUiThread(() -> { if (reconhecedor != null) reconhecedor.stopListening(); });
        }

        @JavascriptInterface public void recarregar() { runOnUiThread(() -> web.loadUrl(urlApp)); }
    }

    @Override
    public void onRequestPermissionsResult(int codigo, String[] perms, int[] res) {
        super.onRequestPermissionsResult(codigo, perms, res);
        if (codigo != REQ_MIC) return;
        boolean ok = res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED;
        if (permissaoWeb != null) {
            if (ok) permissaoWeb.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}); else permissaoWeb.deny();
            permissaoWeb = null;
        }
        if (pedindoParaVoz) {
            pedindoParaVoz = false;
            js("window.__zenVoz&&window.__zenVoz.perm(" + ok + ")");
        }
    }

    @Override
    protected void onActivityResult(int codigo, int resultado, Intent dados) {
        super.onActivityResult(codigo, resultado, dados);
        if (codigo == REQ_ARQUIVO && seletor != null) {
            seletor.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultado, dados));
            seletor = null;
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle b) {
        super.onSaveInstanceState(b);
        web.saveState(b);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();             // garante que o login fica salvo
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (reconhecedor != null) reconhecedor.destroy();
        web.destroy();
        super.onDestroy();
    }
}
