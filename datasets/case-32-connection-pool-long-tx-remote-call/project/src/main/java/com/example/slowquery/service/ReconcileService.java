package com.example.slowquery.service;

import com.example.slowquery.client.PaymentGatewayClient;
import com.example.slowquery.dto.ReconcileResultVO;
import com.example.slowquery.mapper.ReconcileMapper;
import com.example.slowquery.model.ReconcileTask;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ReconcileService {

    private final ReconcileMapper reconcileMapper;
    private final PaymentGatewayClient paymentGatewayClient;

    public ReconcileService(ReconcileMapper reconcileMapper,
                            PaymentGatewayClient paymentGatewayClient) {
        this.reconcileMapper = reconcileMapper;
        this.paymentGatewayClient = paymentGatewayClient;
    }

    @Transactional
    public ReconcileResultVO scanAndSettle(int batchSize) {
        List<ReconcileTask> tasks = reconcileMapper.findPendingTasks(batchSize);
        int processed = 0;
        for (ReconcileTask task : tasks) {
            String gatewayRef = paymentGatewayClient.authorize(task.getOrderNo(), task.getAmount());
            reconcileMapper.markSettled(task.getId(), gatewayRef);
            processed++;
        }
        return new ReconcileResultVO(tasks.size(), processed);
    }
}
