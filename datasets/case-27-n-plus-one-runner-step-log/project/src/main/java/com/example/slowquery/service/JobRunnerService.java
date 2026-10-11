package com.example.slowquery.service;

import com.example.slowquery.dto.JobLogVO;
import com.example.slowquery.dto.RunDetailVO;
import com.example.slowquery.dto.RunJobVO;
import com.example.slowquery.mapper.JobRunnerMapper;
import com.example.slowquery.model.Job;
import com.example.slowquery.model.JobLog;
import com.example.slowquery.model.JobStep;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class JobRunnerService {

    private final JobRunnerMapper jobRunnerMapper;

    public JobRunnerService(JobRunnerMapper jobRunnerMapper) {
        this.jobRunnerMapper = jobRunnerMapper;
    }

    public RunDetailVO runDetails(String runId, int limit) {
        List<Job> jobs = jobRunnerMapper.findRecentJobs(runId, limit);
        RunDetailVO detail = new RunDetailVO();
        detail.setJobs(buildJobViews(jobs));
        detail.setStepTimeline(buildStepTimeline(jobs));
        return detail;
    }

    public List<RunJobVO> buildJobViews(List<Job> jobs) {
        List<RunJobVO> result = new ArrayList<>();
        for (Job job : jobs) {
            List<JobStep> steps = jobRunnerMapper.findStepsByJobId(job.getJobId());
            RunJobVO vo = new RunJobVO();
            vo.setJobId(job.getJobId());
            vo.setJobName(job.getJobName());
            vo.setStepCount(steps.size());
            result.add(vo);
        }
        return result;
    }

    public List<JobLogVO> buildStepTimeline(List<Job> jobs) {
        List<JobLogVO> result = new ArrayList<>();
        for (Job job : jobs) {
            List<JobLog> logs = jobRunnerMapper.findLogsByJobId(job.getJobId());
            JobLogVO vo = new JobLogVO();
            vo.setJobId(job.getJobId());
            vo.setLogCount(logs.size());
            result.add(vo);
        }
        return result;
    }
}
