package com.example.slowquery.mapper;

import com.example.slowquery.model.Job;
import com.example.slowquery.model.JobLog;
import com.example.slowquery.model.JobStep;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface JobRunnerMapper {

    @Select(
        "SELECT job_id, run_id, job_name, created_at_ms FROM jobs " +
        "WHERE run_id = #{runId} " +
        "ORDER BY created_at_ms DESC " +
        "LIMIT #{limit}"
    )
    List<Job> findRecentJobs(@Param("runId") String runId, @Param("limit") int limit);

    @Select(
        "SELECT step_id, job_id, step_name, step_order FROM job_steps " +
        "WHERE job_id = #{jobId} " +
        "ORDER BY step_order"
    )
    List<JobStep> findStepsByJobId(@Param("jobId") Long jobId);

    @Select(
        "SELECT log_id, job_id, level, message, created_at_ms FROM job_logs " +
        "WHERE job_id = #{jobId} " +
        "ORDER BY created_at_ms"
    )
    List<JobLog> findLogsByJobId(@Param("jobId") Long jobId);
}
