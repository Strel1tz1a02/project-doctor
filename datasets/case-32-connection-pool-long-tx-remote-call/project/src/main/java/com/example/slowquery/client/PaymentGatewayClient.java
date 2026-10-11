package com.example.slowquery.client;

import org.springframework.stereotype.Component;

/**
 * 外部支付网关客户端。
 *
 * <p>真实环境下 authorize 会通过 HTTP 同步调用远端支付网关并等待其应答；
 * 本示例用一个固定耗时（{@link #REMOTE_CALL_MS}）的阻塞调用来模拟该远程往返，
 * 以便在本地复现「远程调用耗时」对调用方的影响。</p>
 */
@Component
public class PaymentGatewayClient {

    private static final long REMOTE_CALL_MS = 250L;

    public String authorize(String orderNo, long amount) {
        try {
            Thread.sleep(REMOTE_CALL_MS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return "GW-" + Math.abs((orderNo + amount).hashCode());
    }
}
