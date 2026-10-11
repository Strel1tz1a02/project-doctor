package com.example.slowquery.mapper;

import com.example.slowquery.model.ReconcileTask;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

@Mapper
public interface ReconcileMapper {

    @Select("SELECT id, order_no, amount, status, gateway_ref, created_at_ms FROM reconcile_tasks "
            + "WHERE status = 'PENDING' ORDER BY id LIMIT #{batchSize}")
    List<ReconcileTask> findPendingTasks(@Param("batchSize") int batchSize);

    @Update("UPDATE reconcile_tasks SET status = 'SETTLED', gateway_ref = #{gatewayRef} WHERE id = #{id}")
    int markSettled(@Param("id") long id, @Param("gatewayRef") String gatewayRef);
}
