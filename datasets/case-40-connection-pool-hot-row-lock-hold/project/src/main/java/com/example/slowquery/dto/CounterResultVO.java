package com.example.slowquery.dto;

import lombok.Data;

@Data
public class CounterResultVO {
    private String counterKey;
    private long value;

    public CounterResultVO(String counterKey, long value) {
        this.counterKey = counterKey;
        this.value = value;
    }
}
