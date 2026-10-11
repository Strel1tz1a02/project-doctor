package com.example.slowquery.log;

import org.springframework.stereotype.Component;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.io.Writer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.locks.ReentrantLock;

/**
 * 审计日志门面：所有写入都在同一把全局锁下串行化，并在持锁期间同步刷盘。
 */
@Component
public class AuditLogger {

    /** 全局互斥锁：所有日志写入串行化在同一把锁下。 */
    private static final ReentrantLock MU = new ReentrantLock();

    private final Writer out;

    public AuditLogger() throws IOException {
        Files.createDirectories(Path.of("logs"));
        this.out = new BufferedWriter(new FileWriter("logs/audit.log", true));
    }

    /** 每次写入都持全局锁并同步刷盘。 */
    public void log(String message) {
        MU.lock();
        try {
            out.write(message);
            out.write(System.lineSeparator());
            out.flush();
        } catch (IOException e) {
            throw new IllegalStateException("audit log write failed", e);
        } finally {
            MU.unlock();
        }
    }
}
