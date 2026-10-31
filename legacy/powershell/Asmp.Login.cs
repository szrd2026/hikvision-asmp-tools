using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Asmp {
    // All account/password entry happens in Hikvision's page, never in host code.
    public sealed class LoginWindow : Form {
        private readonly WebView2 browser = new WebView2();
        private readonly Label status = new Label();
        private readonly Timer timer = new Timer();
        private bool reading;
        public string Token { get; private set; }
        public string Error { get; private set; }
        public bool Ready { get; private set; }
        public string PageTitle { get { return browser.CoreWebView2 == null ? "" : browser.CoreWebView2.DocumentTitle; } }

        public LoginWindow(string profileDirectory) {
            Text = "ASMP 官方登录 · 登录成功后自动获取会话";
            Size = new Size(1100, 790);
            StartPosition = FormStartPosition.CenterParent;
            status.Dock = DockStyle.Top;
            status.Height = 42;
            status.Text = "正在载入官网。请在网页完成登录；关闭窗口可取消。";
            browser.Dock = DockStyle.Fill;
            browser.CreationProperties = new CoreWebView2CreationProperties {
                UserDataFolder = profileDirectory,
                IsInPrivateModeEnabled = true
            };
            Controls.Add(browser);
            Controls.Add(status);
            timer.Interval = 800;
            timer.Tick += ReadToken;
            Shown += Initialize;
            FormClosed += delegate { timer.Stop(); timer.Dispose(); browser.Dispose(); };
        }

        private static bool IsOfficial(string url) {
            Uri uri;
            return Uri.TryCreate(url, UriKind.Absolute, out uri) &&
                uri.Scheme == "https" && uri.Host == "asmp.hikvision.com" && uri.Port == 443;
        }

        private async void Initialize(object sender, EventArgs args) {
            try {
                await browser.EnsureCoreWebView2Async(null);
                if (IsDisposed) return;
                browser.CoreWebView2.Settings.IsPasswordAutosaveEnabled = false;
                browser.CoreWebView2.Settings.IsGeneralAutofillEnabled = false;
                browser.CoreWebView2.Settings.AreHostObjectsAllowed = false;
                browser.CoreWebView2.Settings.IsWebMessageEnabled = false;
                browser.CoreWebView2.NavigationStarting += delegate(object s, CoreWebView2NavigationStartingEventArgs e) {
                    if (!IsOfficial(e.Uri)) {
                        e.Cancel = true;
                        status.Text = "已阻止离开 ASMP 官方域名，请在当前网页登录。";
                    }
                };
                browser.CoreWebView2.NewWindowRequested += delegate(object s, CoreWebView2NewWindowRequestedEventArgs e) {
                    e.Handled = true;
                    if (IsOfficial(e.Uri)) browser.CoreWebView2.Navigate(e.Uri);
                };
                browser.CoreWebView2.PermissionRequested += delegate(object s, CoreWebView2PermissionRequestedEventArgs e) {
                    e.State = CoreWebView2PermissionState.Deny;
                };
                browser.CoreWebView2.DownloadStarting += delegate(object s, CoreWebView2DownloadStartingEventArgs e) { e.Cancel = true; };
                browser.CoreWebView2.NavigationCompleted += delegate(object s, CoreWebView2NavigationCompletedEventArgs e) {
                    status.Text = e.IsSuccess ? "请在海康官方网页完成登录。软件只读取 asmp_sr_token，不读取账号或密码。" :
                        "网页加载失败：" + e.WebErrorStatus + "。请检查网络后重新打开登录。";
                };
                Ready = true;
                browser.CoreWebView2.Navigate("https://asmp.hikvision.com/sr/#/receiving/registration");
                timer.Start();
            } catch (Exception e) {
                Error = "登录窗口初始化失败：" + e.GetType().Name + "。请确认已安装 Microsoft Edge WebView2 Runtime。";
                status.Text = Error;
            }
        }

        private async void ReadToken(object sender, EventArgs args) {
            if (reading || browser.CoreWebView2 == null || IsDisposed) return;
            reading = true;
            try {
                string source = browser.CoreWebView2.Source;
                // Do not capture a half-completed password-change/login workflow.
                if (!IsOfficial(source) || !source.Contains("/sr/") || source.Contains("/login")) return;
                var cookies = await browser.CoreWebView2.CookieManager.GetCookiesAsync("https://asmp.hikvision.com/api/sendRepairWeb/");
                if (IsDisposed) return;
                foreach (var cookie in cookies) {
                    if (cookie.Name == "asmp_sr_token" && !String.IsNullOrWhiteSpace(cookie.Value)) {
                        Token = Uri.UnescapeDataString(cookie.Value);
                        DialogResult = DialogResult.OK;
                        Close();
                        return;
                    }
                }
            } catch (Exception) {
                if (!IsDisposed) status.Text = "正在等待登录会话；请完成官网登录。";
            } finally { reading = false; }
        }
    }
}
