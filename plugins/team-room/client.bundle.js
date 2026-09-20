window.__ModuleLoader__.load({
	id: "@meijamke/dsh-team-room",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// client.src.js
var client_src_exports = {};
__export(client_src_exports, {
  apply: () => apply,
  inject: () => inject
});
module.exports = __toCommonJS(client_src_exports);
var import_react = __toESM(require("react"), 1);
var PLUGIN_ID = "@meijamke/dsh-team-room";
var CSS = [
  ".tm-room { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; padding: 16px 20px 8px; color: var(--dsw-alias-label-primary); font-size: var(--dsh-content-font-size, 14px); }",
  ".tm-room * { box-sizing: border-box; }",
  ".tm-room .tm-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }",
  ".tm-room .tm-head h2 { margin: 0; font-size: 16px; font-weight: 600; }",
  ".tm-room .tm-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); color: var(--dsw-alias-label-secondary); font-size: 12px; }",
  ".tm-room .tm-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dsw-alias-label-secondary); }",
  ".tm-room .tm-dot.running { background: var(--dsw-alias-state-success-primary); }",
  ".tm-room .tm-dot.failed { background: var(--dsw-alias-state-error-primary); }",
  ".tm-room .tm-dot.provisioning { background: var(--dsw-alias-brand-primary); }",
  ".tm-room .tm-hint { padding: 12px 14px; border-radius: 12px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); color: var(--dsw-alias-label-secondary); line-height: 1.6; }",
  ".tm-room .tm-feed { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 4px; }",
  ".tm-room .tm-row { display: flex; gap: 8px; align-items: baseline; padding: 6px 10px; border-radius: 10px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); }",
  ".tm-room .tm-row.human { background: var(--dsw-alias-bg-layer-2); }",
  ".tm-room .tm-row.peer { border-left: 2px solid var(--dsw-alias-brand-primary); }",
  ".tm-room .tm-row.status, .tm-room .tm-row.task { background: transparent; border: none; color: var(--dsw-alias-label-secondary); padding: 2px 10px; font-size: 12px; }",
  ".tm-room .tm-who { flex: 0 0 auto; min-width: 84px; color: var(--dsw-alias-label-secondary); font-size: 12px; }",
  ".tm-room .tm-who b { color: var(--dsw-alias-label-primary); font-weight: 600; }",
  ".tm-room .tm-body { flex: 1 1 auto; white-space: pre-wrap; word-break: break-word; line-height: 1.55; min-width: 0; }",
  ".tm-room .tm-meta { color: var(--dsw-alias-label-secondary); font-size: 11px; }",
  ".tm-room .tm-composer { display: flex; gap: 8px; padding: 8px 0 16px; align-items: flex-end; }",
  ".tm-room .tm-composer select, .tm-room .tm-composer textarea, .tm-room .tm-composer button { font: inherit; color: inherit; }",
  ".tm-room .tm-composer select { height: 34px; padding: 0 8px; border-radius: 10px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l2); }",
  ".tm-room .tm-composer textarea { flex: 1 1 auto; min-height: 34px; max-height: 140px; resize: vertical; padding: 7px 10px; border-radius: 10px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l2); }",
  ".tm-room .tm-composer textarea:focus, .tm-room .tm-composer select:focus { outline: none; border-color: var(--dsw-alias-brand-primary); }",
  ".tm-room .tm-composer button { height: 34px; padding: 0 14px; border-radius: 10px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-1); cursor: pointer; }",
  ".tm-room .tm-composer button:disabled { opacity: 0.5; cursor: default; }",
  ".tm-room .tm-error { color: var(--dsw-alias-state-error-primary); font-size: 12px; }"
].join("\n");
var style = document.createElement("style");
style.setAttribute("data-plugin", PLUGIN_ID);
style.textContent = CSS;
document.head.append(style);
var sessionIdCodec = {
  mode: "strict",
  typeSymbol: "@deepseek-ai/dsh-session/types#SessionId",
  schema: { parse: (value) => value }
};
var jsonCodec = {
  mode: "strict",
  typeSymbol: "@meijamke/dsh-team-room#Json",
  schema: { parse: (value) => value }
};
var CONTRIBUTION = {
  package: PLUGIN_ID,
  descriptors: [
    {
      id: PLUGIN_ID + "#teamRoom/feed",
      service: "teamRoom",
      namespace: "teamRoom",
      method: "feed",
      implementation: "feed",
      invocation: { kind: "direct" },
      scope: { context: "agent", wire: "agentId" },
      parameters: [
        { name: "agent", wire: "agentId", source: "lookup", lookup: "agent", codec: sessionIdCodec }
      ],
      result: {
        mode: "strict",
        typeSymbol: "@meijamke/dsh-team-room#FeedResult",
        schema: { parse: (value) => value }
      },
      sourceLocation: { file: "plugins/team-room/client.src.js", line: 1, column: 1 }
    },
    {
      id: PLUGIN_ID + "#teamRoom/send",
      service: "teamRoom",
      namespace: "teamRoom",
      method: "send",
      implementation: "send",
      invocation: { kind: "direct" },
      scope: { context: "agent", wire: "agentId" },
      parameters: [
        { name: "agent", wire: "agentId", source: "lookup", lookup: "agent", codec: sessionIdCodec },
        { name: "request", wire: "request", source: "json", codec: jsonCodec }
      ],
      result: {
        mode: "strict",
        typeSymbol: "@meijamke/dsh-team-room#SendResult",
        schema: { parse: (value) => value }
      },
      sourceLocation: { file: "plugins/team-room/client.src.js", line: 1, column: 1 }
    }
  ]
};
var inject = ["slots", "timer"];
async function apply(ctx) {
  const remote = ctx.get("remote");
  if (remote !== void 0 && typeof remote.$mount === "function") {
    await remote.$mount(CONTRIBUTION);
  }
  function TeamRoomView(props) {
    const sessionId = props.sessionId;
    const [feed, setFeed] = import_react.default.useState(null);
    const [error, setError] = import_react.default.useState(null);
    const [target, setTarget] = import_react.default.useState("lead");
    const [text, setText] = import_react.default.useState("");
    const [sending, setSending] = import_react.default.useState(false);
    const remoteOk = remote !== void 0 && remote.teamRoom !== void 0;
    import_react.default.useEffect(function() {
      let alive = true;
      const load = function() {
        if (!remoteOk) return;
        remote.teamRoom.feed(sessionId).then(function(v) {
          if (!alive) return;
          setFeed(v);
          setError(null);
        }).catch(function(e) {
          if (alive) setError(String(e && e.message ? e.message : e));
        });
      };
      load();
      const stop = ctx.interval(load, 3e3);
      return function() {
        alive = false;
        stop();
      };
    }, [sessionId, remoteOk]);
    const send = function() {
      const value = text.trim();
      if (value === "" || sending) return;
      setSending(true);
      remote.teamRoom.send(sessionId, { targetId: target, text: value }).then(function(r) {
        if (r && r.ok) {
          setText("");
          return remote.teamRoom.feed(sessionId).then(function(v) {
            setFeed(v);
          }).catch(function() {
            return null;
          });
        }
        setError(r && r.error ? r.error : "\u53D1\u9001\u5931\u8D25");
        return null;
      }).catch(function(e) {
        setError(String(e && e.message ? e.message : e));
      }).finally(function() {
        setSending(false);
      });
    };
    const onKey = function(e) {
      if (e && e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    };
    const fmtTime = function(t) {
      if (typeof t !== "number") return "";
      const d = new Date(t);
      const p = function(n) {
        return n < 10 ? "0" + n : String(n);
      };
      return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
    };
    let body;
    if (!remoteOk) {
      body = import_react.default.createElement("div", { className: "tm-hint" }, "Remote \u672A\u6302\u8F7D,\u56E2\u961F\u6C9F\u901A\u4E0D\u53EF\u7528\u3002");
    } else if (feed === null) {
      body = import_react.default.createElement("div", { className: "tm-hint" }, "\u6B63\u5728\u52A0\u8F7D\u56E2\u961F\u6C9F\u901A\u8BB0\u5F55\u2026");
    } else if (feed.ok === false) {
      body = import_react.default.createElement("div", { className: "tm-hint" }, "\u6682\u4E0D\u53EF\u7528\uFF1A" + String(feed.error || "\u672A\u77E5\u539F\u56E0"));
    } else {
      const members = Array.isArray(feed.members) ? feed.members : [];
      const items = Array.isArray(feed.items) ? feed.items : [];
      const tasks = Array.isArray(feed.tasks) ? feed.tasks : [];
      const chips = members.map(function(m) {
        const dotClass = m.status === "running" ? "running" : m.status === "failed" ? "failed" : m.status === "provisioning" ? "provisioning" : "";
        const title = (m.description || "") + (m.model ? " \xB7 " + m.model : "") + (m.diagnostics && m.diagnostics.length ? " \xB7 " + m.diagnostics.join("\uFF1B") : "");
        return import_react.default.createElement(
          "span",
          { key: m.id, className: "tm-chip", title },
          import_react.default.createElement("span", { className: "tm-dot " + dotClass }),
          m.name,
          m.status === "running" ? " \xB7 \u8FD0\u884C\u4E2D" : m.status === "idle" ? " \xB7 \u7A7A\u95F2" : m.status === "inactive" ? " \xB7 \u672A\u8FD0\u884C" : m.status === "provisioning" ? " \xB7 \u521B\u5EFA\u4E2D" : ""
        );
      });
      const rows = items.map(function(item, index) {
        let meta = "";
        if (item.type === "peer") {
          meta = " \u2192 " + (item.meta && item.meta.to ? item.meta.to : "") + (item.meta && item.meta.delivered ? "\uFF08\u5DF2\u9001\u8FBE\uFF09" : "");
        } else if (item.type === "human") {
          meta = " \u2192 " + (item.meta && item.meta.to ? item.meta.to : "");
        }
        return import_react.default.createElement(
          "div",
          { key: index, className: "tm-row " + item.type },
          import_react.default.createElement(
            "span",
            { className: "tm-who" },
            import_react.default.createElement("b", null, item.name),
            import_react.default.createElement("span", { className: "tm-meta" }, " " + fmtTime(item.time) + meta)
          ),
          import_react.default.createElement("div", { className: "tm-body" }, item.text)
        );
      });
      const options = [import_react.default.createElement("option", { value: "lead", key: "lead" }, "\u4E3B Agent")];
      for (const m of members) {
        if (m.role === "teammate") options.push(import_react.default.createElement("option", { value: m.id, key: m.id }, m.name));
      }
      body = import_react.default.createElement(
        import_react.default.Fragment,
        null,
        import_react.default.createElement(
          "div",
          { className: "tm-head" },
          import_react.default.createElement("h2", null, "\u56E2\u961F\u6C9F\u901A"),
          chips
        ),
        feed.hasTeam === false ? import_react.default.createElement(
          "div",
          { className: "tm-hint" },
          feed.serviceReady ? "\u5F53\u524D\u8FD8\u6CA1\u6709\u56E2\u961F\u6210\u5458\u3002\u8BF7\u76F4\u63A5\u544A\u8BC9\u4E3B Agent\uFF1A\u8BA9 TA \u4F7F\u7528 spawn_teammate \u521B\u5EFA\u6210\u5458\uFF08\u4F8B\u5982\u300C\u521B\u5EFA\u4E24\u540D\u6210\u5458\uFF1A\u4E00\u540D\u5199\u4EE3\u7801\u3001\u4E00\u540D\u5BA1\u67E5\u300D\uFF09\u3002\u6210\u5458\u52A0\u5165\u540E\uFF0C\u672C\u9762\u677F\u4F1A\u81EA\u52A8\u5C55\u793A\u6240\u6709\u4F1A\u8BDD\u6D88\u606F\u3001\u6210\u5458\u95F4\u6D88\u606F\u3001\u72B6\u6001\u4E0E\u4EFB\u52A1\u3002" : "Agent Teams \u670D\u52A1\u672A\u52A0\u8F7D\uFF0C\u65E0\u6CD5\u4F7F\u7528\u56E2\u961F\u6C9F\u901A\u3002"
        ) : null,
        tasks.length > 0 ? import_react.default.createElement(
          "div",
          { className: "tm-hint" },
          "\u4EFB\u52A1\uFF1A" + tasks.map(function(t) {
            return t.subject + "\uFF08" + t.status + "\uFF09";
          }).join("\uFF1B")
        ) : null,
        import_react.default.createElement(
          "div",
          { className: "tm-feed" },
          rows.length > 0 ? rows : import_react.default.createElement("div", { className: "tm-hint" }, "\u6682\u65E0\u6C9F\u901A\u8BB0\u5F55")
        ),
        error !== null ? import_react.default.createElement("div", { className: "tm-error" }, error) : null,
        import_react.default.createElement(
          "div",
          { className: "tm-composer" },
          import_react.default.createElement("select", { value: target, onChange: function(e) {
            setTarget(e.target.value);
          } }, options),
          import_react.default.createElement("textarea", {
            value: text,
            placeholder: "\u53D1\u9001\u7ED9\u9009\u4E2D\u7684 Agent\uFF08Enter \u53D1\u9001\uFF0CShift+Enter \u6362\u884C\uFF09",
            onChange: function(e) {
              setText(e.target.value);
            },
            onKeyDown: onKey
          }),
          import_react.default.createElement("button", {
            type: "button",
            disabled: sending || text.trim() === "",
            onClick: send
          }, sending ? "\u53D1\u9001\u4E2D\u2026" : "\u53D1\u9001")
        )
      );
    }
    return import_react.default.createElement("div", { className: "tm-room" }, body);
  }
  const slots = ctx.get("slots");
  if (slots === void 0) return;
  slots.inject("conversation.view", function() {
    return slots.register(
      { name: "conversation.view", id: "team-room", order: 5, label: "\u56E2\u961F\u6C9F\u901A" },
      function(props) {
        return import_react.default.createElement(TeamRoomView, props);
      }
    );
  });
}

		return module.exports;
	}
});
