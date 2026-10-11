package com.example.slowquery.service;

import com.example.slowquery.dto.CounterResultVO;
import com.example.slowquery.mapper.CounterMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CounterService {

    private final CounterMapper counterMapper;

    public CounterService(CounterMapper counterMapper) {
        this.counterMapper = counterMapper;
    }

    @Transactional
    public CounterResultVO incrementHot(String counterKey) {
        Long current = counterMapper.lockByKey(counterKey);
        long nowMs = System.currentTimeMillis();
        if (current == null) {
            counterMapper.insertKey(counterKey, nowMs);
            current = 0L;
        }
        long next = current + 1 + recomputeWindow(current);
        counterMapper.updateValue(counterKey, next, nowMs);
        return new CounterResultVO(counterKey, next);
    }

    private long recomputeWindow(long current) {
        long acc = 0L;
        for (int i = 0; i < 4000; i++) {
            acc += (current + i) % 13;
        }
        return acc % 100;
    }
}
