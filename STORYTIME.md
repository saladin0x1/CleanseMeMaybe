# Storytime: I Fell in Love With PHP Gadget Chains

I got into PHP gadget chains the way most people get into bad habits: slowly, then all at once.

It started with Magento. I was doing bug bounty work, hunting file upload bypasses and extension validation issues. But somewhere along the way I stopped caring about the specific vulnerabilities and started caring about the language itself. PHP. The language everyone loves to hate. But here's the thing about PHP: it's everywhere, it's complex, and it's full of weird object-oriented magic that most people never look at closely.

I started studying how PHP frameworks hydrate objects from user input. How a simple config array can become a fully initialized class instance. How `__construct()`, `__destruct()`, `__call()`, `__toString()`, `__wakeup()` get triggered automatically. How you can chain these magic methods across unrelated classes until one of them does something dangerous like call `shell_exec()` or `eval()` or `file_put_contents()`.

That's a gadget chain. You take a class that does something boring, like typecasting attributes. That class happens to call a method on another class. That class happens to call another method. Three or four hops later, you're at `shell_exec()` with attacker-controlled input. None of the intermediate classes were designed to be dangerous. They just... connect.

I was hooked.

I used AI as a study partner. Not to write exploits, but to explain the mechanics. "How does Yii2's `createObject()` work?" "What happens when you pass an `as something` key in a config array?" "How does Symfony's PropertyAccessor trigger `__call()`?" I was building mental models. Understanding the plumbing. Learning to see the invisible wires connecting objects in a PHP application.

The big frameworks all have their own flavor of this. Laravel has a famous gadget chain through the `__destruct()` path. Symfony has PropertyAccessor-based chains. Drupal has render array injection. Yii2, which powers Craft CMS, has a particularly elegant one: config arrays with special keys.

In Yii2, when you create an object through `Yii::createObject()`, you can pass a config array. The framework walks the array and applies it to the object. But it also interprets two special key prefixes:

- `as name` attaches a behavior (a reusable component) to the object
- `on event` registers an event handler

This is by design. It's a feature. But if an attacker controls that config array, they can attach arbitrary behaviors and register arbitrary event handlers. And if one of those behaviors happens to have a method that calls `shell_exec()`...

That's the gadget. `as rce` → `AttributeTypecastBehavior` → `ConsoleProcessus::execute()` → `shell_exec()`. Four classes. None of them meant to be exploitable. All of them just doing their job. Connected by PHP's magic method dispatch.

I found CVE-2026-33157 through this research. Someone had already reported that you could inject `as` and `on` keys directly into condition arrays in Craft CMS. Craft patched it in 5.10.1 by adding `Component::cleanseConfig()`, a sanitizer that strips any array key starting with `as ` or `on `.

I downloaded 5.10.1 to test the patch. Because that's what you do. You don't trust patches. You verify them.

I traced the code. `ElementSearchController` calls `cleanseConfig()` on the condition array, then passes it to `Conditions::createCondition()`. Direct array keys with `as` or `on` were getting stripped. I confirmed it with a canary. Gone. Good patch.

But then I saw this:

```php
// Conditions.php
$configJson = ArrayHelper::remove($config, 'config');
if ($configJson !== null) {
    $config = ArrayHelper::merge($config, Json::decode($configJson));
}
```

The condition array has a field called `config`. Not a sub-array. A JSON string.

`cleanseConfig()` walks array keys. It finds `as something` and removes them. But `config` is just `config`. Its value is a string. The cleanse doesn't parse JSON. It sees a normal string and moves on.

Then `createCondition()` decodes that JSON and merges it back in. After the cleanse. Without re-cleansing.

The JSON can contain anything. Including `as rce` and `on *` keys that the sanitize was designed to remove. But already ran. On the wrong data.

It was 3AM. I laughed so hard my cat left the room.

You don't bypass the sanitizer with encoding tricks or unicode magic or any clever hack. You just put the payload in a format the sanitizer doesn't inspect. It's like a security guard who checks your backpack but not your jacket because the policy says "check backpacks."

I built a canary first. Non-executing payload pointing to a nonexistent class. Direct array version: stripped, working as intended. JSON version: Yii threw "class not found." The canary reached the framework. The bypass was confirmed.

Then the full gadget chain. `psy/psysh` ships in Craft's dependencies and has `ConsoleProcessus::execute()` which calls `shell_exec()`. It pipes through `escapeshellcmd()`, so no shell metacharacters. But `/usr/bin/script -q -c id /path/to/webroot/output.txt` works fine. `script` is a real binary. No `>`, no `|`, no `;`. Just a command and an output file.

I fired it in Burp Repeater:

```
POST /admin/actions/element-search/search
```

Response: `{"elements":[],"exactMatch":false}`

HTTP 200. Normal. Like nothing happened.

Then I opened `/craft_burp_id.txt`.

```
uid=501(user) gid=20(dialout) groups=20(dialout)
```

Command execution. Web user. Non-admin account. Through a JSON string that the framework's own sanitizer was supposed to clean.

**Then came the disclosure part.**

Reported to Craft CMS VDP on May 19, 2026. Four days after 5.10.1 shipped. Full source references. Burp requests. Differential proof. The whole thing.

Triager acknowledged on May 21. Then on May 26, closed as duplicate of #1244. No technical explanation. No comparison. Just "unfortunately this was submitted previously."

I asked: does #1244 specifically include the `condition.config` JSON decode-after-cleanse variant in Craft 5.10.1?

No response.

I asked again. Filed mediation.

No response.

I checked the git history myself. Four releases since 5.10.1. Zero changes to any file in the vulnerable path. `Component.php`, `Conditions.php`, `ElementSearchController.php`, `ElementCondition.php`. All untouched.

The bug is still there. Still exploitable. Latest release.

I started this journey fascinated by how PHP objects connect. How magic methods create invisible wires between classes. How a typecaster can lead to a process executor can lead to a shell. And I found a real RCE by understanding those wires better than the people who wrote them.

Then I learned a different lesson. Sometimes the hardest part isn't finding the bug. It's getting someone to read the report.

The code doesn't lie. The git history doesn't lie. And `uid=501(user)` in my webroot doesn't lie.

---

*CleanseMeMaybe. Because sometimes the sanitize function is just a suggestion.*
