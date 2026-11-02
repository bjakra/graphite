#!/usr/bin/env bash
# Run Gradle in the Lawnchair port worktree with settings gentle enough to share the
# machine with a ROM build. Output is filtered to errors; full log in logs/lawnchair-gradle.log.
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
cd "$G/apps/lawnchair-a17" || exit 1
export JAVA_HOME="$G/src/prebuilts/jdk/jdk21/linux-x86" ANDROID_HOME="$G/sdk" GRADLE_USER_HOME="$G/sdk/gradle-home"
nice -n 10 ./gradlew --no-daemon --max-workers="${GRADLE_WORKERS:-2}" --console=plain \
    -Dorg.gradle.jvmargs="-Xmx${GRADLE_HEAP:-3g} -Xss${GRADLE_STACK:-16m} ${GRADLE_JVM_EXTRA:-} -Dfile.encoding=UTF-8" \
    -Pkotlin.compiler.execution.strategy=in-process "$@" > "$G/logs/lawnchair-gradle.log" 2>&1
rc=$?
grep -E "^e: |error:|\* What went wrong|^> |FAILED|BUILD (SUCCESSFUL|FAILED)|invalid|not allowed" "$G/logs/lawnchair-gradle.log" \
    | grep -vE '^> Task .*(UP-TO-DATE|NO-SOURCE|FROM-CACHE)?$|Run with|Get more help' | sed "s#file://$PWD/##; s#$PWD/##" | cut -c1-210 | head -"${GRADLE_LINES:-60}"
exit $rc
